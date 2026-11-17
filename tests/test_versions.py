import unittest
from product.app import Application

MERCHANTS = ['k1', 'k2', 'k3', 'k4', 'k5']
PLAN = {'cells': [{'name': 'total-change', 'recipients': ['alliance'],
                   'terms': [{'week': '2026-W42'}, {'week': '2026-W41', 'sign': -1}]}]}


def fixture(app):
    sectors = ['food', 'food', 'sport', 'sport', 'hotel']
    for merchant, sector in zip(MERCHANTS, sectors):
        app.execute('panel.register', dict(id=merchant, sector=sector, district='east',
                                           opened='2026-01-01'))
    for index, merchant in enumerate(MERCHANTS):
        app.execute('submissions.report', dict(id=f's-{merchant}-41', merchant=merchant,
                                               week='2026-W41', cents=1000 * (index + 1),
                                               open_days=7))
        if merchant != 'k5':
            app.execute('submissions.report', dict(id=f's-{merchant}-42', merchant=merchant,
                                                   week='2026-W42', cents=1100 * (index + 1),
                                                   open_days=7))
    app.execute('growth.analyze', dict(id='g1', base_week='2026-W41', compare_week='2026-W42',
                                       merchants=MERCHANTS))
    app.execute('disclosure.assess', dict(id='d1', growth='g1', plan=PLAN))


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        fixture(self.app)

    def tearDown(self):
        self.app.store.close()

    def prepare_and_send(self, id, disclosure='d1', supersedes=None):
        arguments = dict(id=id, disclosure=disclosure, reviewer='finance')
        if supersedes:
            arguments['supersedes'] = supersedes
        self.app.execute('distribution.prepare', arguments)
        return self.app.execute('distribution.send', dict(id=id))

    def test_correction_marks_sent_release_but_keeps_payload(self):
        sent = self.prepare_and_send('r1')
        original = sent['payload']['cells'][0]['value']
        self.app.execute('submissions.correct', dict(id='s-k1-42', cents=1500,
                                                     reason='对账更正'))
        release = self.app.store.get('release', 'r1')
        self.assertEqual(release['state'], 'corrected')
        self.assertEqual(release['payload']['cells'][0]['value'], original)
        self.assertEqual(release['corrections'][0]['source'], 's-k1-42')
        self.assertEqual(release['corrections'][0]['kind'], 'submission')

    def test_unsent_release_follows_valid_analysis(self):
        self.app.execute('distribution.prepare', dict(id='r2', disclosure='d1',
                                                      reviewer='finance'))
        self.app.execute('submissions.correct', dict(id='s-k1-42', cents=1500,
                                                     reason='对账更正'))
        with self.assertRaisesRegex(ValueError, '报送已更正'):
            self.app.execute('distribution.send', dict(id='r2'))
        self.assertEqual(self.app.store.get('release', 'r2')['state'], 'prepared')

    def test_late_report_blocks_send(self):
        self.app.execute('distribution.prepare', dict(id='r2', disclosure='d1',
                                                      reviewer='finance'))
        self.app.execute('submissions.report', dict(id='s-k5-42', merchant='k5',
                                                    week='2026-W42', cents=900, open_days=6))
        with self.assertRaisesRegex(ValueError, '报送集合已变化'):
            self.app.execute('distribution.send', dict(id='r2'))

    def test_merge_revision_marks_sent_and_blocks_prepared(self):
        self.prepare_and_send('r1')
        self.app.execute('distribution.prepare', dict(id='r2', disclosure='d1',
                                                      reviewer='finance'))
        self.app.execute('panel.register', dict(id='k9', sector='food', district='east',
                                                opened='2026-10-12'))
        self.app.execute('panel.merge', dict(id='k1', successors=['k9'],
                                             effective='2026-10-12'))
        self.assertEqual(self.app.store.get('release', 'r1')['state'], 'corrected')
        self.assertEqual(self.app.store.get('release', 'r1')['corrections'][0]['kind'],
                         'merchant')
        with self.assertRaisesRegex(ValueError, '承接关系已修订'):
            self.app.execute('distribution.send', dict(id='r2'))

    def test_superseded_versions_are_comparable(self):
        first = self.prepare_and_send('r1')
        self.app.execute('submissions.correct', dict(id='s-k1-42', cents=1500,
                                                     reason='对账更正'))
        self.app.execute('growth.analyze', dict(id='g2', base_week='2026-W41',
                                                compare_week='2026-W42', merchants=MERCHANTS))
        self.app.execute('disclosure.assess', dict(id='d2', growth='g2', plan=PLAN))
        second = self.prepare_and_send('r2', disclosure='d2', supersedes='r1')
        old = self.app.store.get('release', 'r1')
        self.assertEqual(old['state'], 'corrected')
        self.assertEqual(old['superseded_by'], 'r2')
        self.assertEqual(second['version'], 2)
        diff = self.app.execute('distribution.compare', dict(id='r1', other='r2'))
        self.assertEqual(diff['versions'], {'r1': 1, 'r2': 2})
        changed = {c['name']: c for c in diff['cells']['changed']}
        self.assertEqual(changed['total-change']['r1'],
                         first['payload']['cells'][0]['value'])
        self.assertEqual(changed['total-change']['r2'],
                         second['payload']['cells'][0]['value'])
        self.assertEqual(diff['corrections']['r1'][0]['source'], 's-k1-42')
        self.assertEqual(diff['corrections']['r2'], [])

    def test_compare_rejects_mixed_kinds(self):
        self.prepare_and_send('r1')
        self.app.execute('statistics.summarize', dict(id='sum1', week='2026-W41',
                                                      merchants=['k1', 'k2']))
        self.app.execute('distribution.prepare', dict(id='legacy', summary='sum1',
                                                      recipients=['alliance'],
                                                      reviewer='finance'))
        self.app.execute('distribution.send', dict(id='legacy'))
        with self.assertRaisesRegex(ValueError, '版本类型不同'):
            self.app.execute('distribution.compare', dict(id='r1', other='legacy'))


if __name__ == '__main__':
    unittest.main()
