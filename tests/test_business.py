import json
import unittest
from pathlib import Path
from product.app import Application


class BusinessBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.app=Application()
        self.app.replay(json.loads((Path(__file__).parent.parent/'data'/'demo.json').read_text()))

    def tearDown(self):
        self.app.store.close()
    def test_correction_blocks_prepared_release(self):
        self.app.execute('distribution.prepare',dict(id='r2',summary='sum1',recipients=['second'],reviewer='finance'))
        self.app.execute('submissions.correct',dict(id='s1',cents=90000,reason='对账更正'))
        with self.assertRaises(ValueError):
            self.app.execute('distribution.send',dict(id='r2'))
        self.assertEqual(self.app.store.get('release','r1')['payload']['cents'],100000)

    def test_missing_and_zero_are_distinct(self):
        self.app.execute('submissions.report',dict(id='s3',merchant='m2',week='2026-W43',cents=0,open_days=7))
        summary=self.app.execute('statistics.summarize',dict(id='sum2',week='2026-W43',merchants=['m2']))
        self.assertEqual((summary['reported'],summary['missing'],summary['cents']),(1,0,0))
