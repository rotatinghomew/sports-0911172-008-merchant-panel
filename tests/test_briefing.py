import json
import unittest
from pathlib import Path
from product.app import Application

DATA = Path(__file__).parent.parent / 'data' / 'briefing.json'


class BriefingDemoTests(unittest.TestCase):
    """赛事周场景：面板增长主要来自新接入大店，同店增长温和。"""

    @classmethod
    def setUpClass(cls):
        cls.app = Application()
        cls.results = cls.app.replay(json.loads(DATA.read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.app.store.close()

    def test_panel_change_is_decomposed_not_headlined(self):
        growth = self.app.store.get('growth', 'g1')
        self.assertEqual(growth['totals']['change'], 854000)
        self.assertEqual(growth['same_store']['change'], 59000)
        self.assertEqual(growth['entry']['amount'], 30000)
        self.assertEqual(growth['exit']['amount'], 15000)
        self.assertEqual(growth['partial']['change'], 780000)
        self.assertEqual(growth['same_store']['open_days_effect']
                         + growth['same_store']['day_rate_effect'], 59000)
        self.assertTrue(any('全城消费增长' in w for w in growth['warnings']))

    def test_split_merge_unit_is_paired(self):
        growth = self.app.store.get('growth', 'g1')
        units = {u['key']: u for u in growth['units']}
        self.assertEqual(units['p1+p1a+p1b']['status'], 'paired')
        self.assertEqual((units['p1+p1a+p1b']['base'], units['p1+p1a+p1b']['compare']),
                         (70000, 75000))
        self.assertEqual(units['h3']['status'], 'partial')
        self.assertEqual(units['f4']['status'], 'partial')
        self.assertEqual(units['f5']['status'], 'exit')
        self.assertEqual(units['p4']['status'], 'entry')

    def test_disclosure_suppresses_jointly_unsafe_cells(self):
        assessment = self.app.store.get('disclosure', 'd1')
        suppressed = {c['name']: c['rule'] for c in assessment['suppressed']}
        self.assertEqual(suppressed['hotel-w44'], 'dominance')
        self.assertEqual(suppressed['entry-change'], 'count')
        self.assertEqual(suppressed['partial-change'], 'count')
        self.assertEqual(suppressed['food-w44'], 'complementary')
        publishable = [c['name'] for c in assessment['publishable']]
        self.assertEqual(publishable,
                         ['total-w44', 'sport-w44', 'samestore-change', 'panel-change'])

    def test_correction_flow_marks_and_supersedes(self):
        old = self.app.store.get('release', 'br1')
        new = self.app.store.get('release', 'br2')
        self.assertEqual(old['state'], 'corrected')
        self.assertEqual(old['corrections'][0]['source'], 'bw-f1-44')
        self.assertEqual(old['superseded_by'], 'br2')
        self.assertEqual((old['version'], new['version'], new['state']), (1, 2, 'sent'))
        self.assertEqual(new['payload']['supersedes'], 'br1')

    def test_compare_explains_version_difference(self):
        diff = self.app.execute('distribution.compare', dict(id='br1', other='br2'))
        changed = {c['name']: c for c in diff['cells']['changed']}
        self.assertEqual(changed['samestore-change'], {'name': 'samestore-change',
                                                       'br1': 59000, 'br2': 64000})
        self.assertEqual(changed['total-w44']['br2'] - changed['total-w44']['br1'], 5000)
        self.assertNotIn('sport-w44', changed)
        self.assertEqual(diff['corrections']['br1'][0]['kind'], 'submission')
        self.assertEqual(diff['state'], {'br1': 'corrected', 'br2': 'sent'})

    def test_outward_briefing_has_no_membership_detail(self):
        release = self.app.store.get('release', 'br1')
        text = json.dumps(release['payload'], ensure_ascii=False)
        for merchant in ('f1', 'f4', 'h3', 'p1a'):
            self.assertNotIn(merchant, text)
        self.assertTrue(release['payload']['suppressed'])
        self.assertTrue(release['payload']['assumptions'])


if __name__ == '__main__':
    unittest.main()
