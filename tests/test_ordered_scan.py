import csv,io,unittest
from pathlib import Path
from employer_sources import structured,Sink,vendor
from ordered_scan import india,location

class OrderedTests(unittest.TestCase):
    def test_registry(self):
        rows=list(csv.DictReader(io.StringIO(Path('config/employers.csv').read_text())))
        self.assertEqual(len(rows),100);self.assertEqual(len({r['name'] for r in rows}),100)
        self.assertTrue(all(r['careers_url'].startswith('https://') for r in rows))
    def test_country(self):
        self.assertTrue(india('MH, IN'));self.assertTrue(india('Mumbai, India'))
        self.assertFalse(india('Hyderabad, Texas, USA'))
        self.assertIn('India',location({'city':'Mumbai','country':'India'}))
    def test_structured(self):
        text='<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"VP Credit Risk","url":"/job/1","datePosted":"2026-11-10T01:00:00Z","jobLocation":{"address":{"addressCountry":"India"}}}]}</script>'
        rows,_=structured(text,'https://example.org/careers','Example')
        self.assertEqual(rows[0]['date_posted'],'2026-11-10T01:00:00Z')
        self.assertEqual(rows[0]['job_url'],'https://example.org/job/1')
    def test_stream(self):
        saved=[];sink=Sink(saved.append);sink.append({'id':1})
        self.assertEqual(len(saved),1);self.assertEqual(len(sink),1);self.assertEqual(list(sink),[])
    def test_update_is_not_posting(self):
        class Response:
            def json(self):return {'jobs':[{'id':1,'title':'Credit Risk VP','absolute_url':'https://example.org/job/1','updated_at':'2026-11-10T01:00:00Z','content':'credit risk','location':{'name':'India'}}]}
        class FakeClient:
            def request(self,url):
                if 'content=true' in url:return Response()
                class Detail:
                    def json(self):return {'updated_at':'2026-11-10T01:00:00Z'}
                return Detail()
        rows=[];vendor('https://boards.greenhouse.io/example','Example',FakeClient(),rows.append)
        self.assertEqual(rows[0]['date_posted'],'')
if __name__=='__main__':unittest.main()
