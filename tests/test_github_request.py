import unittest
from datetime import datetime, timezone
from github_scan_request import request_id, dispatch_allowed

class RequestTests(unittest.TestCase):
    identifier='12345678-1234-1234-1234-123456789abc'
    def event(self,login,title):
        return {'repository':{'owner':{'login':'sup-gaurav'}},'issue':{'user':{'login':login},'title':title}}
    def test_owner_only(self):
        title='[SCAN] '+self.identifier
        self.assertEqual(request_id(self.event('sup-gaurav',title)),self.identifier)
        self.assertIsNone(request_id(self.event('someone-else',title)))
    def test_untrusted_title(self):
        self.assertIsNone(request_id(self.event('sup-gaurav','[SCAN] $(echo secret)')))
    def test_active_and_cooldown(self):
        now=datetime(2026,11,9,18,tzinfo=timezone.utc)
        self.assertFalse(dispatch_allowed([{'status':'in_progress'}],now)[0])
        self.assertFalse(dispatch_allowed([{'status':'completed','created_at':'2026-11-09T17:59:00Z'}],now)[0])
        self.assertTrue(dispatch_allowed([{'status':'completed','created_at':'2026-11-09T17:00:00Z'}],now)[0])
        self.assertTrue(dispatch_allowed([],now)[0])
if __name__=='__main__':unittest.main()
