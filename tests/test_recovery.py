import ast,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from scan_recovery import defer_source,ready,advance,finish,mark_deferred,transform

class RecoveryTests(unittest.TestCase):
    now=datetime(2026,11,10,3,tzinfo=timezone.utc)
    def state(self):return {'phase':0,'query_index':0,'offset':350,'items':{'saved':{'id':'saved'}},'board_coverage':{}}
    def test_429_continues_other_sources(self):
        state=self.state();defer_source(state,'linkedin',0,['credit risk','Citi credit risk'],self.now)
        self.assertEqual(state['deferred_boards']['linkedin']['offset'],350)
        self.assertFalse(ready(state,'linkedin',self.now+timedelta(minutes=10)))
        self.assertTrue(ready(state,'indeed',self.now))
        advance(state,0);self.assertEqual(state['phase'],1)
        self.assertIn('saved',state['items'])
    def test_resume_and_no_false_zero(self):
        state=self.state();defer_source(state,'linkedin',0,['credit risk','Citi credit risk'],self.now)
        state['employer_index']=100;finish(state)
        self.assertEqual(state['offset'],350);self.assertFalse(state['pass_finished'])
        self.assertTrue(ready(state,'linkedin',self.now+timedelta(hours=2)))
        self.assertEqual(state['board_coverage']['linkedin:1']['state'],'deferred_rate_limit')
    def test_completed_source_skips(self):
        state={'completed_boards':['indeed']}
        self.assertFalse(ready(state,'indeed',self.now))
        finish(state);self.assertTrue(state['pass_finished'])
    def test_installed_coordinator(self):
        path=Path('ordered_scan.py')
        if not path.exists():self.skipTest('Coordinator is checked in CI')
        code=transform(path.read_text());ast.parse(code)
        self.assertEqual(transform(code),code)
        self.assertNotIn("raise Paused('Rate limited; saved page cursor",code)
        self.assertIn('mark_deferred(state,source,queries)',code)
if __name__=='__main__':unittest.main()
