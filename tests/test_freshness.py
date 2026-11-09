import unittest
from datetime import datetime, timedelta, timezone
from freshness import assess

class FreshnessTests(unittest.TestCase):
    now=datetime(2026,11,9,17,13,tzinfo=timezone.utc)
    def test_recent(self):
        self.assertEqual(assess({'date_posted':'2026-11-09T12:00:00+00:00'},self.now)['status'],'within_48h')
    def test_old_never_rediscovered(self):
        self.assertEqual(assess({'date_posted':'2026-11-05','last_seen':self.now.isoformat(),'first_seen':self.now.isoformat()},self.now)['status'],'older_than_48h')
    def test_exact_boundary(self):
        self.assertEqual(assess({'date_posted':(self.now-timedelta(hours=48)).isoformat()},self.now)['status'],'within_48h')
    def test_over_boundary(self):
        self.assertEqual(assess({'date_posted':(self.now-timedelta(hours=48,seconds=1)).isoformat()},self.now)['status'],'older_than_48h')
    def test_missing(self):
        self.assertEqual(assess({'posted_at':self.now.isoformat(),'last_seen':self.now.isoformat()},self.now)['status'],'date_unverified')
    def test_date_uncertainty(self):
        self.assertEqual(assess({'date_posted':'2026-11-08'},self.now)['status'],'boundary_unverified')
        self.assertEqual(assess({'date_posted':'2026-11-09'},self.now)['status'],'within_48h')
    def test_repost(self):
        self.assertEqual(assess({'date_posted':'2026-11-01','source_reposted_at':'2026-11-09T12:00:00Z','repost_evidence_url':'https://example.org/job/1'},self.now)['event'],'reposted')
        self.assertEqual(assess({'date_posted':'2026-11-01','source_reposted_at':'2026-11-09T12:00:00Z'},self.now)['status'],'older_than_48h')
    def test_naive_and_future(self):
        for value in ['2026-11-09T12:00:00','2099-01-01T00:00:00Z','2 days ago']:
            self.assertEqual(assess({'date_posted':value},self.now)['status'],'date_unverified')
if __name__=='__main__':unittest.main()
