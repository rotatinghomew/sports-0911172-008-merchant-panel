from .store import require
from .disclosure import recheck

COVERAGE_FIELDS = ('requested', 'units', 'paired', 'entry', 'exit', 'partial', 'inactive',
                   'same_store_base_share')


class Distribution:
    def __init__(self, store):
        self.store = store

    def prepare(self, id, summary=None, disclosure=None, recipients=None, reviewer=None,
                supersedes=None):
        require(bool(reviewer), '分发授权为空')
        require((summary is None) != (disclosure is None), '须指定汇总或披露评估之一')
        if summary is not None:
            record = self.store.get('summary', summary)
            require(bool(recipients), '分发授权为空')
            return self.store.put('release', id, dict(
                summary=summary, payload=record, recipients=recipients,
                reviewer=reviewer, state='prepared', version=1), create=True)
        assessment = self.store.get('disclosure', disclosure)
        require(bool(assessment['publishable']), '无可披露内容')
        derived = sorted({r for cell in assessment['publishable'] for r in cell['recipients']})
        if recipients is not None:
            require(sorted(recipients) == derived, '收件人与披露评估不一致')
        growth = self.store.get('growth', assessment['growth']['id'])
        require(growth['revision'] == assessment['growth']['revision'], '分析已更新，需重新评估')
        version = 1
        if supersedes is not None:
            version = self.store.get('release', supersedes).get('version', 1) + 1
        published = [cell['name'] for cell in assessment['publishable']]
        payload = {
            'kind': 'briefing',
            'growth': assessment['growth'],
            'disclosure': {'id': assessment['id'], 'revision': assessment['revision']},
            'weeks': [growth['base_week'], growth['compare_week']],
            'cells': [{'name': c['name'], 'value': c['value'], 'merchants': c['merchants'],
                       'recipients': c['recipients'],
                       'terms': [self._outward_term(t) for t in c['terms']]}
                      for c in assessment['publishable']],
            'suppressed': [{'name': c['name'], 'reason': c['reason']}
                           for c in assessment['suppressed']],
            'coverage': {k: growth['coverage'][k] for k in COVERAGE_FIELDS}
                        | {'missing_reports': len(growth['coverage']['missing_reports'])},
            'assumptions': growth['assumptions'] + assessment['assumptions'],
            'warnings': growth['warnings'],
            'version': version,
            'supersedes': supersedes,
        }
        return self.store.put('release', id, dict(
            disclosure=disclosure, payload=payload,
            resolved=assessment['resolved'], published=published,
            rules=assessment['rules'],
            recipients=derived, reviewer=reviewer, state='prepared',
            sources={'submissions': dict(growth['sources']['submissions']),
                     'merchants': dict(growth['sources']['merchants'])},
            version=version, supersedes=supersedes), create=True)

    @staticmethod
    def _outward_term(term):
        outward = {k: v for k, v in term.items() if k != 'merchants'}
        if 'merchants' in term:
            outward['merchants'] = len(term['merchants'])
        return outward

    def send(self, id):
        with self.store.atomic():
            record = self.store.get('release', id)
            if record['state'] in ('sent', 'corrected'):
                return record
            payload = record['payload']
            if payload.get('kind') == 'briefing':
                self._check_briefing(record)
            else:
                for source, revision in payload['sources'].items():
                    require(self.store.get('submission', source)['revision'] == revision,
                            '报送已更正，需重新准备')
            for recipient in record['recipients']:
                self.store.put('dispatch', f'{id}:{recipient}',
                               dict(release=id, recipient=recipient), create=True)
            record['state'] = 'sent'
            if record.get('supersedes'):
                old = self.store.get('release', record['supersedes'])
                if old['state'] in ('sent', 'corrected'):
                    old['superseded_by'] = id
                    self.store.put('release', old['id'], old)
            return self.store.put('release', id, record)

    def _check_briefing(self, record):
        payload = record['payload']
        growth = self.store.get('growth', payload['growth']['id'])
        require(growth['revision'] == payload['growth']['revision'],
                '分析已更新，需重新评估与准备')
        assessment = self.store.get('disclosure', payload['disclosure']['id'])
        require(assessment['revision'] == payload['disclosure']['revision'],
                '披露评估已更新，需重新准备')
        for source, revision in record['sources']['submissions'].items():
            require(self.store.get('submission', source)['revision'] == revision,
                    '报送已更正，需重新评估与准备')
        current = {item['id'] for item in self.store.all('submission')
                   if item['merchant'] in record['sources']['merchants']
                   and item['week'] in payload['weeks']}
        require(current == set(record['sources']['submissions']),
                '报送集合已变化，需重新评估与准备')
        for merchant, revision in record['sources']['merchants'].items():
            require(self.store.get('merchant', merchant)['revision'] == revision,
                    '承接关系已修订，需重新评估与准备')
        require(recheck(self.store, record), '披露环境已变化，需重新评估')

    def compare(self, id, other):
        first = self.store.get('release', id)
        second = self.store.get('release', other)
        result = {
            'versions': {id: first.get('version', 1), other: second.get('version', 1)},
            'state': {id: first['state'], other: second['state']},
            'superseded_by': {id: first.get('superseded_by'), other: second.get('superseded_by')},
            'corrections': {id: first.get('corrections', []),
                            other: second.get('corrections', [])},
        }
        first_payload, second_payload = first['payload'], second['payload']
        if first_payload.get('kind') == 'briefing' and second_payload.get('kind') == 'briefing':
            first_cells = {c['name']: c['value'] for c in first_payload['cells']}
            second_cells = {c['name']: c['value'] for c in second_payload['cells']}
            result['cells'] = {
                'changed': [{'name': name, id: first_cells[name], other: second_cells[name]}
                            for name in sorted(first_cells.keys() & second_cells.keys())
                            if first_cells[name] != second_cells[name]],
                'only_in_first': sorted(first_cells.keys() - second_cells.keys()),
                'only_in_second': sorted(second_cells.keys() - first_cells.keys()),
            }
            result['suppressed'] = {
                id: [s['name'] for s in first_payload['suppressed']],
                other: [s['name'] for s in second_payload['suppressed']],
            }
        elif 'cents' in first_payload and 'cents' in second_payload:
            result['summary'] = {
                field: {id: first_payload[field], other: second_payload[field]}
                for field in ('cents', 'reported', 'missing')}
        else:
            raise ValueError('版本类型不同，无法核对')
        return result
