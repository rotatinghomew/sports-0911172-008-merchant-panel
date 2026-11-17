import re
from datetime import date
from fractions import Fraction
from .store import require

WEEK_PATTERN = re.compile(r'^(\d{4})-W(\d{2})$')

ASSUMPTIONS = [
    '缺报视为未知：缺报商户不按零销售计入任何总额',
    '同店口径：报送单元在两周的全部在营成员均已报送',
    '承接口径：生效日介于两期之间的拆并按报送单元合并比较，拆并本身不产生进出',
    '部分缺报单元的已观测金额单列，不并入同店，也不按零处理',
    '进出单元按已观测报送金额计量，停报商户的未知金额不在任何总额中',
    '营业天数效应按对称分解（Bennet）计算并取整到分，残差计入日均经营效应',
    '行业构成以基期行业为准，跨行业承接单元单列 mixed',
    '结果仅描述所选商户的报送面板，不代表未纳入商户，不能表述为全城消费增长',
]


def week_bounds(week):
    match = WEEK_PATTERN.match(week)
    require(match is not None, '周格式无效')
    year, number = int(match.group(1)), int(match.group(2))
    try:
        start = date.fromisocalendar(year, number, 1)
    except ValueError:
        raise ValueError('周格式无效') from None
    return start, date.fromisocalendar(year, number, 7)


def active_during(record, start, end):
    """营业区间按 [opened, closed) 理解，与周有交集视为当周在营。"""
    opened = date.fromisoformat(record['opened'])
    closed = date.fromisoformat(record['closed']) if record['closed'] else None
    return opened <= end and (closed is None or closed > start)


def ratio(change, base):
    return round(change / base, 6) if base else None


def unit_sector(attributes, members):
    names = {attributes[m]['sector'] for m in members}
    return names.pop() if len(names) == 1 else 'mixed'


class Growth:
    """可比增长分析：把面板总变化分解为同店、进出、行业构成与营业天数。"""

    def __init__(self, store):
        self.store = store

    def analyze(self, id, base_week, compare_week, merchants):
        require(bool(merchants) and len(merchants) == len(set(merchants)), '研究对象无效')
        base_start, base_end = week_bounds(base_week)
        comp_start, comp_end = week_bounds(compare_week)
        require(base_start < comp_start, '对比周须晚于基期周')
        records = {key: self.store.get('merchant', key) for key in merchants}
        scope = set(merchants)

        units, unscoped = self._units(records, merchants, base_end, comp_end)

        submissions = {}
        sources_submissions = {}
        for item in self.store.all('submission'):
            if item['merchant'] in scope and item['week'] in (base_week, compare_week):
                submissions[(item['merchant'], item['week'])] = item
                sources_submissions[item['id']] = item['revision']

        attributes = {key: {'sector': records[key]['sector'], 'district': records[key]['district']}
                      for key in merchants}
        observed = {base_week: {}, compare_week: {}}
        missing_reports = []
        details = []
        for members in units:
            detail = self._classify(
                members, records, submissions, base_week, compare_week,
                (base_start, base_end), (comp_start, comp_end), unscoped)
            details.append(detail)
            for week, side in ((base_week, 'base'), (compare_week, 'compare')):
                for merchant, cents in detail[f'{side}_reported'].items():
                    observed[week][merchant] = cents
            missing_reports.extend(detail['missing'])

        totals = {
            'base': sum(observed[base_week].values()),
            'compare': sum(observed[compare_week].values()),
        }
        totals['change'] = totals['compare'] - totals['base']
        totals['rate'] = ratio(totals['change'], totals['base'])

        grouped = {status: [d for d in details if d['status'] == status]
                   for status in ('paired', 'entry', 'exit', 'partial', 'inactive')}
        same_store = self._same_store(grouped['paired'])
        entry = self._one_sided(grouped['entry'], 'compare', attributes)
        exit_ = self._one_sided(grouped['exit'], 'base', attributes)
        partial = {
            'units': [d['key'] for d in grouped['partial']],
            'base': sum(d['base'] for d in grouped['partial']),
            'compare': sum(d['compare'] for d in grouped['partial']),
        }
        partial['change'] = partial['compare'] - partial['base']
        require(totals['change'] == same_store['change'] + entry['amount']
                - exit_['amount'] + partial['change'], '分解恒等式不成立')

        coverage = {
            'requested': len(merchants),
            'units': len(details),
            'paired': len(grouped['paired']),
            'entry': len(grouped['entry']),
            'exit': len(grouped['exit']),
            'partial': len(grouped['partial']),
            'inactive': len(grouped['inactive']),
            'inactive_merchants': sorted(m for d in grouped['inactive'] for m in d['members']),
            'missing_reports': sorted(missing_reports, key=lambda m: (m['week'], m['merchant'])),
            'unscoped_successors': unscoped,
            'same_store_base_share': ratio(same_store['base'], totals['base']),
        }
        entity = dict(
            base_week=base_week, compare_week=compare_week, merchants=list(merchants),
            attributes=attributes, totals=totals, same_store=same_store,
            entry=entry, exit=exit_, partial=partial,
            mix=self._mix(grouped['paired'], attributes, same_store),
            units=[self._unit_view(d) for d in details],
            coverage=coverage, assumptions=list(ASSUMPTIONS),
            warnings=self._warnings(same_store, entry, exit_, partial, coverage),
            observed=observed,
            sources={'submissions': sources_submissions,
                     'merchants': {key: records[key]['revision'] for key in merchants}},
        )
        return self.store.put('growth', id, entity, create=True)

    def _units(self, records, merchants, base_end, comp_end):
        scope = set(merchants)
        parent = {key: key for key in merchants}

        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        unscoped = []
        for key in merchants:
            record = records[key]
            if not record['successors']:
                continue
            effective = date.fromisoformat(record['closed'])
            if not (base_end < effective <= comp_end):
                continue
            for successor in record['successors']:
                if successor in scope:
                    parent[find(key)] = find(successor)
                else:
                    unscoped.append({'merchant': key, 'successor': successor})
        groups = {}
        for key in merchants:
            groups.setdefault(find(key), []).append(key)
        return [sorted(members) for members in groups.values()], unscoped

    def _classify(self, members, records, submissions, base_week, compare_week,
                  base, compare, unscoped):
        def side(week, bounds):
            active = [m for m in members if active_during(records[m], *bounds)]
            reported, missing = {}, []
            for merchant in members:
                item = submissions.get((merchant, week))
                if item is not None and item['status'] == 'reported':
                    reported[merchant] = item['cents']
            for merchant in active:
                if merchant in reported:
                    continue
                item = submissions.get((merchant, week))
                missing.append({'merchant': merchant, 'week': week,
                                'reason': item['status'] if item is not None else '未报送'})
            days = sum(submissions[(m, week)]['open_days'] for m in reported)
            return active, reported, missing, days

        base_active, base_reported, base_missing, base_days = side(base_week, base)
        comp_active, comp_reported, comp_missing, comp_days = side(compare_week, compare)
        if not base_active and not comp_active:
            status, reason = 'inactive', '两期均无在营成员'
        elif base_active and comp_active:
            if not base_missing and not comp_missing:
                status, reason = 'paired', '两期完整报送'
            else:
                status = 'partial'
                reason = '；'.join(self._missing_text('基期', base_missing)
                                  + self._missing_text('对比期', comp_missing))
        elif comp_active:
            if not comp_missing:
                status, reason = 'entry', '基期无在营成员（新开业或新接入）'
            else:
                status = 'partial'
                reason = '；'.join(['基期无在营成员'] + self._missing_text('对比期', comp_missing))
        else:
            if not base_missing:
                status = 'exit'
                reason = '对比期无在营成员（已关闭或被承接出范围）'
                dropped = sorted(u['successor'] for u in unscoped if u['merchant'] in members)
                if dropped:
                    reason += f"；承接门店未纳入研究范围: {','.join(dropped)}"
            else:
                status = 'partial'
                reason = '；'.join(['对比期无在营成员'] + self._missing_text('基期', base_missing))
        return dict(key='+'.join(members), members=list(members), status=status, reason=reason,
                    base=sum(base_reported.values()), compare=sum(comp_reported.values()),
                    base_days=base_days, compare_days=comp_days,
                    base_active=base_active, compare_active=comp_active,
                    base_reported=base_reported, compare_reported=comp_reported,
                    missing=base_missing + comp_missing)

    @staticmethod
    def _missing_text(label, missing):
        if not missing:
            return []
        merchants = ','.join(sorted(m['merchant'] for m in missing))
        return [f'{label}缺报: {merchants}']

    def _same_store(self, paired):
        base = sum(d['base'] for d in paired)
        compare = sum(d['compare'] for d in paired)
        days_effect = Fraction(0)
        undecomposed = 0
        undecomposed_units = []
        for unit in paired:
            change = unit['compare'] - unit['base']
            if unit['base_days'] and unit['compare_days']:
                days_effect += (unit['compare_days'] - unit['base_days']) * (
                    Fraction(unit['base'], unit['base_days'])
                    + Fraction(unit['compare'], unit['compare_days'])) / 2
            else:
                undecomposed += change
                undecomposed_units.append(unit['key'])
        days_rounded = int(round(days_effect))
        return {
            'units': [d['key'] for d in paired],
            'base': base, 'compare': compare, 'change': compare - base,
            'rate': ratio(compare - base, base),
            'open_days_effect': days_rounded,
            'day_rate_effect': compare - base - undecomposed - days_rounded,
            'undecomposed_change': undecomposed,
            'undecomposed_units': undecomposed_units,
        }

    @staticmethod
    def _one_sided(details, side, attributes):
        by_sector = {}
        for detail in details:
            members = detail[f'{side}_active'] or detail['members']
            sector = unit_sector(attributes, members)
            by_sector[sector] = by_sector.get(sector, 0) + detail[side]
        return {'units': [d['key'] for d in details],
                'amount': sum(d[side] for d in details),
                'by_sector': by_sector}

    @staticmethod
    def _mix(paired, attributes, same_store):
        sectors = {}
        for detail in paired:
            sector = unit_sector(attributes, detail['base_active'] or detail['members'])
            bucket = sectors.setdefault(sector, {'base': 0, 'compare': 0})
            bucket['base'] += detail['base']
            bucket['compare'] += detail['compare']
        average = (Fraction(same_store['change'], same_store['base'])
                   if same_store['base'] else None)
        mix = []
        for sector in sorted(sectors):
            bucket = sectors[sector]
            change = bucket['compare'] - bucket['base']
            benchmark = int(round(average * bucket['base'])) if average is not None else None
            mix.append({'sector': sector, 'base': bucket['base'], 'compare': bucket['compare'],
                        'change': change, 'benchmark': benchmark,
                        'excess': change - benchmark if benchmark is not None else None})
        return mix

    @staticmethod
    def _warnings(same_store, entry, exit_, partial, coverage):
        warnings = []
        if not same_store['units']:
            warnings.append('两期无完全可比单元，同店口径不可用')
        share = coverage['same_store_base_share']
        if share is not None and share < 0.8:
            warnings.append('同店口径覆盖不足基期观测额的八成，同店变化不能代表所选面板整体')
        non_comparable = abs(entry['amount']) + abs(exit_['amount']) + abs(partial['change'])
        if non_comparable > abs(same_store['change']):
            warnings.append('面板总变化主要来自进出或缺报等非可比部分，不得解释为同店增长')
        if coverage['missing_reports']:
            warnings.append('存在缺报，相关商户金额未知，未按零计入')
        warnings.append('结果仅描述所选报送面板，不能表述为全城消费增长')
        return warnings

    @staticmethod
    def _unit_view(detail):
        return {'key': detail['key'], 'members': detail['members'], 'status': detail['status'],
                'reason': detail['reason'], 'base': detail['base'], 'compare': detail['compare'],
                'base_days': detail['base_days'], 'compare_days': detail['compare_days'],
                'base_active': detail['base_active'], 'compare_active': detail['compare_active']}
