import os, unittest
from unittest.mock import patch
from free_scan import normalize, durable_prepare
from free_adapters import supplements

class FreeFirstTests(unittest.TestCase):
    def test_country_code(self):
        self.assertIn('India',normalize({'location':'MH, IN'})['location'])
        self.assertEqual(normalize({'location':'London, GB'})['location'],'London, GB')
    def test_preserve_evidence(self):
        old={'id':'saved','title':'Senior Manager Credit Risk','company':'Citi','location':'MH, IN','job_url':'https://example.org/job/1','match_score':100,'eligibility':'needs_review','gates':{'domain':True,'seniority':True,'india':False},'gaps':['India work location/eligibility needs verification'],'description_available':True,'description_excerpt':'SAS validation evidence','first_seen':'2026-11-01','last_seen':'2026-11-02'}
        out=durable_prepare([old])[0]
        self.assertEqual(out['description_excerpt'],'SAS validation evidence')
        self.assertEqual(out['eligibility'],'eligible')
        self.assertEqual(out['first_seen'],'2026-11-01')
        self.assertNotIn('India work location/eligibility needs verification',out['gaps'])
    def test_optional_apis_off(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return []
        with patch.dict(os.environ,{},clear=True),patch('free_adapters.requests.get',return_value=Response()) as get,patch('free_adapters.time.sleep'):
            rows,health=supplements()
            self.assertEqual(rows,[])
            self.assertEqual(get.call_count,2)
            self.assertEqual(health['serpapi']['status'],'not_enabled_or_configured')
            self.assertEqual(health['adzuna']['status'],'not_enabled_or_configured')
            self.assertEqual(health['naukri_direct']['status'],'interaction_required')
if __name__=='__main__':unittest.main()
