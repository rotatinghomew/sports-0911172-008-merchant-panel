import unittest
from product.app import Application

SCOPE = ['a', 'b', 'c', 'd', 'e']


def fixture(app):
    app.execute('panel.register', dict(id='a', sector='food', district='east', opened='2026-01-01'))
    app.execute('panel.register', dict(id='b', sector='food', district='east', opened='2026-01-01'))
    app.execute('panel.register', dict(id='c', sector='sport', district='east', opened='2026-01-01'))
    app.execute('panel.register', dict(id='d', sector='sport', district='west', opened='2026-01-01'))
    app.execute('panel.register', dict(id='e', sector='hotel', district='west', opened='2026-10-12'))
    app.execute('submissions.report', dict(id='s-a-41', merchant='a', week='2026-W41', cents=1000, open_days=7))
    app.execute('submissions.report', dict(id='s-b-41', merchant='b', week='2026-W41', cents=800, open_days=5))
    app.execute('submissions.report', dict(id='s-c-41', merchant='c', week='2026-W41', cents=500, open_days=5))
    app.execute('submissions.report', dict(id='s-d-41', merchant='d', week='2026-W41', cents=400, open_days=4))
    app.execute('submissions.report', dict(id='s-a-42', merchant='a', week='2026-W42', cents=1100, open_days=7))
    app.execute('submissions.report', dict(id='s-b-42', merchant='b', week='2026-W42', cents=None, open_days=0, status='missing'))
    app.execute('submissions.report', dict(id='s-c-42', merchant='c', week='2026-W42', cents=600, open_days=6))
    app.execute('submissions.report', dict(id='s-d-42', merchant='d', week='2026-W42', cents=440, open_days=4))
    app.execute('submissions.report', dict(id='s-e-42', merchant='e', week='2026-W42', cents=2000, open_days=7))
    return app.execute('growth.analyze', dict(id='g1', base_week='2026-W41',
                                              compare_week='2026-W42', merchants=SCOPE))


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.growth = fixture(self.app)

    def tearDown(self):
        self.app.store.close()

    def test_decomposition_identity(self):
        g = self.growth
        self.assertEqual((g['totals']['base'], g['totals']['compare'], g['totals']['change']),
                         (2700, 4140, 1440))
        parts = (g['same_store']['change'] + g['entry']['amount']
                 - g['exit']['amount'] + g['partial']['change'])
        self.assertEqual(parts, g['totals']['change'])
        self.assertEqual((g['same_store']['base'], g['same_store']['compare'],
                          g['same_store']['change']), (1900, 2140, 240))

    def test_missing_is_not_zero(self):
        g = self.growth
        self.assertEqual(g['partial'], {'units': ['b'], 'base': 800, 'compare': 0,
                                        'change': -800})
        missing = {(m['merchant'], m['week']) for m in g['coverage']['missing_reports']}
        self.assertEqual(missing, {('b', '2026-W42')})
        self.assertNotIn('b', g['observed']['2026-W42'])
        self.assertTrue(any('缺报' in a for a in g['assumptions']))

    def test_open_days_effect_is_exact(self):
        same = self.growth['same_store']
        self.assertEqual(same['open_days_effect'], 100)
        self.assertEqual(same['day_rate_effect'], 140)
        self.assertEqual(same['open_days_effect'] + same['day_rate_effect']
                         + same['undecomposed_change'], same['change'])

    def test_mix_benchmark_sums_to_same_store_change(self):
        mix = self.growth['mix']
        self.assertEqual([m['sector'] for m in mix], ['food', 'sport'])
        self.assertEqual(sum(m['change'] for m in mix), 240)
        self.assertEqual(sum(m['benchmark'] for m in mix), 240)
        self.assertEqual(sum(m['excess'] for m in mix), 0)

    def test_entry_exit_buckets(self):
        g = self.growth
        self.assertEqual(g['entry'], {'units': ['e'], 'amount': 2000,
                                      'by_sector': {'hotel': 2000}})
        self.assertEqual(g['exit'], {'units': [], 'amount': 0, 'by_sector': {}})

    def test_coverage_and_warnings_explain_scope(self):
        g = self.growth
        coverage = g['coverage']
        self.assertEqual((coverage['requested'], coverage['paired'], coverage['entry'],
                          coverage['partial']), (5, 3, 1, 1))
        self.assertAlmostEqual(coverage['same_store_base_share'], 1900 / 2700, places=6)
        text = '\n'.join(g['warnings'] + g['assumptions'])
        self.assertIn('不能表述为全城消费增长', text)
        self.assertIn('非可比部分', '\n'.join(g['warnings']))

    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):
            self.app.execute('growth.analyze', dict(id='g2', base_week='2026-W42',
                                                    compare_week='2026-W41', merchants=SCOPE))
        with self.assertRaises(ValueError):
            self.app.execute('growth.analyze', dict(id='g2', base_week='2026-10-05',
                                                    compare_week='2026-W42', merchants=SCOPE))
        with self.assertRaises(ValueError):
            self.app.execute('growth.analyze', dict(id='g2', base_week='2026-W41',
                                                    compare_week='2026-W42',
                                                    merchants=['a', 'a']))
        with self.assertRaises(ValueError):
            self.app.execute('growth.analyze', dict(id='g2', base_week='2026-W41',
                                                    compare_week='2026-W42', merchants=['zz']))
        with self.assertRaises(ValueError):
            self.app.execute('growth.analyze', dict(id='g1', base_week='2026-W41',
                                                    compare_week='2026-W42', merchants=SCOPE))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.app.execute('panel.register', dict(id='m', sector='food', district='east', opened='2026-01-01'))
        self.app.execute('panel.register', dict(id='x', sector='food', district='east', opened='2026-10-12'))
        self.app.execute('panel.register', dict(id='y', sector='food', district='east', opened='2026-10-12'))
        self.app.execute('panel.merge', dict(id='m', successors=['x', 'y'], effective='2026-10-12'))
        self.app.execute('submissions.report', dict(id='s-m-41', merchant='m', week='2026-W41', cents=700, open_days=7))
        self.app.execute('submissions.report', dict(id='s-x-42', merchant='x', week='2026-W42', cents=400, open_days=7))
        self.app.execute('submissions.report', dict(id='s-y-42', merchant='y', week='2026-W42', cents=350, open_days=7))

    def tearDown(self):
        self.app.store.close()

    def test_split_merge_creates_no_fake_entry(self):
        g = self.app.execute('growth.analyze', dict(id='g', base_week='2026-W41',
                                                    compare_week='2026-W42',
                                                    merchants=['m', 'x', 'y']))
        self.assertEqual(g['same_store']['change'], 50)
        self.assertEqual(g['entry']['amount'], 0)
        self.assertEqual(g['exit']['amount'], 0)
        self.assertEqual(g['same_store']['units'], ['m+x+y'])

    def test_unscoped_successor_is_explained_exit(self):
        g = self.app.execute('growth.analyze', dict(id='g', base_week='2026-W41',
                                                    compare_week='2026-W42', merchants=['m']))
        self.assertEqual(g['exit']['amount'], 700)
        self.assertEqual(g['same_store']['change'], 0)
        self.assertEqual(len(g['coverage']['unscoped_successors']), 2)
        unit = g['units'][0]
        self.assertEqual(unit['status'], 'exit')
        self.assertIn('承接门店未纳入研究范围', unit['reason'])


if __name__ == '__main__':
    unittest.main()
