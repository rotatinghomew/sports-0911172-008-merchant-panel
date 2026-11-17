from fractions import Fraction
from .store import require

DEFAULT_RULES = {'min_merchants': 3, 'dominance': 0.5}

REASONS = {
    'count': '覆盖商户数低于披露阈值',
    'dominance': '单一商户占比过高',
    'differencing': '与本次或历史披露内容联立可反推个别商户金额',
    'complementary': '为保护其他未披露内容而作的互补隐藏',
}

DISCLOSURE_ASSUMPTIONS = [
    '披露检查按收件人独立进行，未防范收件人之间的串谋',
    '差分检查覆盖精确推导：单个商户金额及少于阈值的商户组合金额',
    '同一收件人历史已发送内容纳入联立检查，发送前会复核披露环境',
]


def unit_key(merchant, week):
    return f'{merchant}|{week}'


class Basis:
    """有理数域上的行空间，用于精确判断某个金额能否被联立推导。"""

    def __init__(self):
        self.rows = {}

    def _reduce(self, vec):
        vec = {c: v for c, v in vec.items() if v}
        while vec:
            pivots = [c for c in vec if c in self.rows]
            if not pivots:
                break
            col = min(pivots)
            factor = vec[col]
            row = self.rows[col]
            vec = {c: vec.get(c, Fraction(0)) - factor * row.get(c, Fraction(0))
                   for c in set(vec) | set(row)}
            vec = {c: v for c, v in vec.items() if v}
        return vec

    def add(self, vec):
        remainder = self._reduce({c: Fraction(v) for c, v in vec.items() if v})
        if not remainder:
            return
        pivot = min(remainder)
        norm = remainder[pivot]
        row = {c: v / norm for c, v in remainder.items()}
        for key, other in list(self.rows.items()):
            if pivot in other:
                factor = other[pivot]
                merged = {c: other.get(c, Fraction(0)) - factor * row.get(c, Fraction(0))
                          for c in set(other) | set(row)}
                self.rows[key] = {c: v for c, v in merged.items() if v}
        self.rows[pivot] = row

    def remainder(self, vec):
        return self._reduce({c: Fraction(v) for c, v in vec.items() if v})

    def contains(self, vec):
        return not self.remainder(vec)


def _direction(remainder):
    pivot = min(remainder)
    scale = remainder[pivot]
    return tuple(sorted((c, v / scale) for c, v in remainder.items()))


def exposures(rows, units, min_merchants=3):
    """返回（可单推的商户-周， 可两两联推的组合）。少于阈值的组合视为暴露。"""
    basis = Basis()
    for row in rows:
        basis.add(row)
    remainders = {unit: basis.remainder({unit: 1}) for unit in units}
    singles = {unit for unit, rem in remainders.items() if not rem}
    pairs = set()
    if min_merchants >= 3:
        groups = {}
        for unit, rem in remainders.items():
            if rem:
                groups.setdefault(_direction(rem), set()).add(unit)
        for group in groups.values():
            if len(group) > 1:
                for first in group:
                    for second in group:
                        if first < second:
                            pairs.add((first, second))
    return singles, pairs


def contains(rows, vec):
    basis = Basis()
    for row in rows:
        basis.add(row)
    return basis.contains(vec)


def past_rows(store, exclude=None):
    """同一收件人已经拿到的内容：已发送的简报单元，以及旧版汇总（按范围上限还原）。"""
    rows = {}
    for release in store.all('release'):
        if release['id'] == exclude or release['state'] not in ('sent', 'corrected'):
            continue
        if 'resolved' in release:
            published = set(release.get('published', []))
            for cell in release['resolved']:
                if cell['name'] not in published:
                    continue
                for recipient in cell['recipients']:
                    rows.setdefault(recipient, []).append(
                        {'label': f"{release['id']}:{cell['name']}", 'units': cell['units']})
        else:
            payload = release['payload']
            if 'merchants' in payload and 'week' in payload:
                units = {unit_key(m, payload['week']): 1 for m in payload['merchants']}
                for recipient in release['recipients']:
                    rows.setdefault(recipient, []).append(
                        {'label': f"{release['id']}:legacy", 'units': units})
    return rows


def _violated_units(past, remaining, hidden, recipients, min_merchants):
    """当前候选发布集下的违规：返回（暴露的商户-周集合， 是否有被隐藏内容可推导）。"""
    violated = set()
    hidden_derivable = False
    for recipient in recipients:
        past_rec = [row['units'] for row in past.get(recipient, [])]
        rows = past_rec + [c['units'] for c in remaining if recipient in c['recipients']]
        units = sorted({u for row in rows for u in row})
        past_units = sorted({u for row in past_rec for u in row})
        known_s, known_p = exposures(past_rec, past_units, min_merchants)
        known = known_s | {u for pair in known_p for u in pair}
        new_s, new_p = exposures(rows, units, min_merchants)
        violated |= (new_s | {u for pair in new_p for u in pair}) - known
        for cell in hidden:
            if recipient in cell['recipients'] and cell['units']:
                if contains(rows, cell['units']) and not contains(past_rec, cell['units']):
                    violated |= set(cell['units'])
                    hidden_derivable = True
    return violated, hidden_derivable


def recheck(store, record):
    """发送前复核：自评估以来披露环境（含其他已发送简报）是否仍然安全。"""
    past = past_rows(store, exclude=record['id'])
    published = [c for c in record['resolved'] if c['name'] in record['published']]
    hidden = [c for c in record['resolved'] if c['name'] not in record['published']]
    rules = record.get('rules', DEFAULT_RULES)
    for recipient in record['recipients']:
        past_rec = [row['units'] for row in past.get(recipient, [])]
        rows = past_rec + [c['units'] for c in published if recipient in c['recipients']]
        units = sorted({u for row in rows for u in row})
        past_units = sorted({u for row in past_rec for u in row})
        known_s, known_p = exposures(past_rec, past_units, rules['min_merchants'])
        known = known_s | {u for pair in known_p for u in pair}
        new_s, new_p = exposures(rows, units, rules['min_merchants'])
        if (new_s | {u for pair in new_p for u in pair}) - known:
            return False
        for cell in hidden:
            if recipient in cell['recipients'] and cell['units']:
                if contains(rows, cell['units']) and not contains(past_rec, cell['units']):
                    return False
    return True


class Disclosure:
    """联合披露保护：阈值、集中度与跨期跨范围的联立差分检查。"""

    def __init__(self, store):
        self.store = store

    def assess(self, id, growth, plan, rules=None):
        record = self.store.get('growth', growth)
        rules = dict(DEFAULT_RULES, **(rules or {}))
        require(rules['min_merchants'] in (2, 3), '披露阈值仅支持2或3')
        require(isinstance(rules['dominance'], (int, float))
                and not isinstance(rules['dominance'], bool)
                and 0 < rules['dominance'] < 1, '集中度阈值无效')
        cells = plan.get('cells') if isinstance(plan, dict) else plan
        require(bool(cells), '披露计划为空')
        require(len({c.get('name') for c in cells}) == len(cells), '披露内容名称重复')
        resolved = [self._resolve(cell, record) for cell in cells]

        suppressed = {}
        for cell in resolved:
            if len(cell['members']) < rules['min_merchants']:
                suppressed[cell['name']] = 'count'
            elif all(v > 0 for v in cell['units'].values()) and cell['value'] > 0:
                amounts = {}
                for key in cell['units']:
                    merchant, week = key.rsplit('|', 1)
                    amounts[merchant] = (amounts.get(merchant, 0)
                                         + record['observed'][week][merchant])
                if max(amounts.values()) / cell['value'] > rules['dominance']:
                    suppressed[cell['name']] = 'dominance'

        past = past_rows(self.store)
        recipients = sorted({r for c in resolved for r in c['recipients']} | set(past))
        pre_existing = []
        for recipient in recipients:
            rows = [row['units'] for row in past.get(recipient, [])]
            units = sorted({u for row in rows for u in row})
            if not units:
                continue
            singles, pairs = exposures(rows, units, rules['min_merchants'])
            exposed = singles | {u for pair in pairs for u in pair}
            if exposed:
                pre_existing.append({'recipient': recipient, 'units': len(exposed)})

        remaining = [c for c in resolved if c['name'] not in suppressed]
        hidden = [c for c in resolved if c['name'] in suppressed]
        violated, hidden_derivable = _violated_units(
            past, remaining, hidden, recipients, rules['min_merchants'])
        while violated:
            best, best_key = None, None
            for index, cell in enumerate(remaining):
                trial = [c for c in remaining if c is not cell]
                outcome, _ = _violated_units(past, trial, hidden + [cell], recipients,
                                             rules['min_merchants'])
                key = (len(outcome), len(cell['members']), index)
                if best_key is None or key < best_key:
                    best, best_key = cell, key
            require(best is not None and best_key[0] < len(violated),
                    '现有披露已存在风险，无法通过隐藏新内容修复')
            suppressed[best['name']] = 'complementary' if hidden_derivable else 'differencing'
            hidden.append(best)
            remaining.remove(best)
            violated, hidden_derivable = _violated_units(
                past, remaining, hidden, recipients, rules['min_merchants'])

        publishable = [c for c in resolved if c['name'] not in suppressed]
        entity = dict(
            growth={'id': record['id'], 'revision': record['revision']},
            rules=rules,
            publishable=[{'name': c['name'], 'recipients': c['recipients'],
                          'value': c['value'], 'merchants': len(c['members']),
                          'terms': c['terms']} for c in publishable],
            suppressed=[{'name': c['name'], 'recipients': c['recipients'],
                         'rule': suppressed[c['name']],
                         'reason': REASONS[suppressed[c['name']]]} for c in resolved
                        if c['name'] in suppressed],
            pre_existing=pre_existing,
            assumptions=list(DISCLOSURE_ASSUMPTIONS),
            resolved=[{'name': c['name'], 'recipients': c['recipients'], 'units': c['units']}
                      for c in resolved],
        )
        return self.store.put('disclosure', id, entity, create=True)

    def _resolve(self, cell, record):
        name = cell.get('name')
        recipients = cell.get('recipients')
        terms = cell.get('terms')
        require(bool(name), '披露内容名称无效')
        require(bool(recipients), '披露收件人为空')
        require(bool(terms), '披露内容缺少统计口径')
        weeks = (record['base_week'], record['compare_week'])
        units, members, value = {}, set(), 0
        for term in terms:
            week = term.get('week')
            require(week in weeks, '披露周超出分析范围')
            sign = term.get('sign', 1)
            require(sign in (1, -1), '披露口径系数仅支持正负一')
            for merchant in self._select(term, record):
                cents = record['observed'].get(week, {}).get(merchant)
                if cents is None:
                    continue
                key = unit_key(merchant, week)
                units[key] = units.get(key, 0) + sign
                members.add(merchant)
                value += sign * cents
        units = {k: v for k, v in units.items() if v}
        return {'name': name, 'recipients': sorted(set(recipients)), 'terms': terms,
                'units': units, 'members': sorted(members), 'value': value}

    @staticmethod
    def _select(term, record):
        keys = [k for k in ('merchants', 'sector', 'district', 'units') if k in term]
        require(len(keys) <= 1, '披露口径每次仅使用一种选择器')
        if not keys:
            return list(record['merchants'])
        key = keys[0]
        if key == 'merchants':
            selected = term['merchants']
            require(bool(selected) and set(selected) <= set(record['merchants']),
                    '披露对象超出研究范围')
            return selected
        if key == 'sector':
            return [m for m in record['merchants']
                    if record['attributes'][m]['sector'] == term['sector']]
        if key == 'district':
            return [m for m in record['merchants']
                    if record['attributes'][m]['district'] == term['district']]
        require(term['units'] in ('paired', 'entry', 'exit', 'partial'), '未知单元口径')
        return sorted({m for unit in record['units'] if unit['status'] == term['units']
                       for m in unit['members']})
