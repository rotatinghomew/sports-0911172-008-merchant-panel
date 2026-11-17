import unittest
from product.app import Application

MERCHANTS = ['v1', 'v2', 'v3', 'v4', 'v5']


def fixture(app):
    sectors = ['food', 'food', 'sport', 'sport', 'sport']
    for merchant, sector in zip(MERCHANTS, sectors):
        app.execute('panel.register', dict(id=merchant, sector=sector, district='east',
                                           opened='2026-01-01'))
    amounts = {'v1': 1000, 'v2': 900, 'v3': 800, 'v4': 700, 'v5': 600}
    for merchant, cents in amounts.items():
        app.execute('submissions.report', dict(id=f's-{merchant}-41', merchant=merchant,
                                               week='2026-W41', cents=cents, open_days=7))
        app.execute('submissions.report', dict(id=f's-{merchant}-42', merchant=merchant,
                                               week='2026-W42', cents=cents + 100, open_days=7))
    app.execute('growth.analyze', dict(id='g', base_week='2026-W41', compare_week='2026-W42',
                                       merchants=MERCHANTS))


def cell(name, recipients, merchants, week='2026-W42'):
    return {'name': name, 'recipients': recipients,
            'terms': [{'week': week, 'merchants': merchants}]}


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        fixture(self.app)

    def tearDown(self):
        self.app.store.close()

    def assess(self, id, cells, rules=None):
        arguments = dict(id=id, growth='g', plan={'cells': cells})
        if rules:
            arguments['rules'] = rules
        return self.app.execute('disclosure.assess', arguments)

    def test_count_rule_and_partial_results(self):
        result = self.assess('d1', [
            cell('small', ['r1'], ['v1', 'v2']),
            cell('total', ['r1'], MERCHANTS),
        ])
        self.assertEqual([c['name'] for c in result['publishable']], ['total'])
        suppressed = {c['name']: c for c in result['suppressed']}
        self.assertEqual(suppressed['small']['rule'], 'count')
        self.assertEqual(suppressed['small']['reason'], '覆盖商户数低于披露阈值')
        self.assertNotIn('v1', suppressed['small']['reason'])

    def test_dominance_rule(self):
        result = self.assess('d1', [cell('top', ['r1'], ['v1', 'v2', 'v3'])],
                             rules={'dominance': 0.3})
        self.assertEqual(result['publishable'], [])
        self.assertEqual(result['suppressed'][0]['rule'], 'dominance')

    def test_complementary_suppression_hides_more_than_one_cell(self):
        result = self.assess('d1', [
            cell('total', ['r1'], MERCHANTS),
            cell('food', ['r1'], ['v1', 'v2']),
            cell('sport', ['r1'], ['v3', 'v4', 'v5']),
        ])
        rules = {c['name']: c['rule'] for c in result['suppressed']}
        self.assertEqual(rules['food'], 'count')
        self.assertEqual(rules['sport'], 'complementary')
        self.assertEqual([c['name'] for c in result['publishable']], ['total'])

    def test_recipients_checked_independently(self):
        separated = self.assess('d1', [
            cell('total', ['r1'], MERCHANTS),
            cell('part', ['r2'], ['v1', 'v2', 'v3']),
        ])
        self.assertEqual([c['name'] for c in separated['publishable']], ['total', 'part'])
        shared = self.assess('d2', [
            cell('total', ['r1'], MERCHANTS),
            cell('part', ['r1'], ['v1', 'v2', 'v3']),
        ])
        self.assertEqual([c['name'] for c in shared['publishable']], ['total'])
        self.assertEqual(shared['suppressed'][0]['rule'], 'differencing')

    def test_longitudinal_differencing_uses_sent_history(self):
        first = self.assess('d1', [cell('part', ['r1'], ['v1', 'v2', 'v3'])])
        self.app.execute('distribution.prepare', dict(id='rel1', disclosure='d1',
                                                      reviewer='finance'))
        self.app.execute('distribution.send', dict(id='rel1'))
        second = self.assess('d2', [cell('total', ['r1'], MERCHANTS)])
        self.assertEqual(second['publishable'], [])
        self.assertEqual(second['suppressed'][0]['rule'], 'differencing')

    def test_send_rechecks_disclosure_environment(self):
        self.assess('d1', [cell('part', ['r1'], ['v1', 'v2', 'v3'])])
        self.assess('d2', [cell('total', ['r1'], MERCHANTS)])
        self.app.execute('distribution.prepare', dict(id='rel1', disclosure='d1',
                                                      reviewer='finance'))
        self.app.execute('distribution.prepare', dict(id='rel2', disclosure='d2',
                                                      reviewer='finance'))
        self.app.execute('distribution.send', dict(id='rel1'))
        with self.assertRaisesRegex(ValueError, '披露环境已变化'):
            self.app.execute('distribution.send', dict(id='rel2'))
        self.assertEqual(self.app.store.get('release', 'rel2')['state'], 'prepared')

    def test_outward_payload_hides_membership(self):
        self.assess('d1', [
            cell('part', ['r1'], ['v1', 'v2', 'v3']),
            cell('small', ['r1'], ['v4', 'v5']),
        ])
        self.app.execute('distribution.prepare', dict(id='rel1', disclosure='d1',
                                                      reviewer='finance'))
        release = self.app.store.get('release', 'rel1')
        payload = release['payload']
        self.assertEqual(payload['cells'][0]['terms'][0]['merchants'], 3)
        self.assertNotIn('v1', str(payload['cells']))
        self.assertNotIn('v4', str(payload['suppressed']))
        self.assertEqual(payload['suppressed'][0]['reason'], '覆盖商户数低于披露阈值')

    def test_plan_validation(self):
        with self.assertRaises(ValueError):
            self.assess('d1', [cell('x', ['r1'], ['v1', 'v2'], week='2026-W40')])
        with self.assertRaises(ValueError):
            self.assess('d1', [cell('x', ['r1'], ['v1', 'zz'])])
        with self.assertRaises(ValueError):
            self.assess('d1', [cell('x', ['r1'], ['v1']), cell('x', ['r1'], ['v2'])])
        with self.assertRaises(ValueError):
            self.assess('d1', [{'name': 'x', 'recipients': ['r1'],
                                'terms': [{'week': '2026-W42', 'sector': 'food',
                                           'district': 'east'}]}])
        with self.assertRaises(ValueError):
            self.assess('d1', [cell('x', ['r1'], MERCHANTS)], rules={'min_merchants': 9})


if __name__ == '__main__':
    unittest.main()
