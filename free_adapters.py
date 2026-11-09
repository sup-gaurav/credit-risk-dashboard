import html, json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests

BOARDS=[('PayU','https://api.eu.lever.co/v0/postings/payu'),('OakNorth','https://api.lever.co/v0/postings/oaknorth.ai')]

def text(value):return html.unescape(re.sub('<[^>]+>',' ',str(value or ''))).strip()

def supplements():
    rows,health=[],{}
    for company,url in BOARDS:
        label='lever:'+company
        try:
            response=requests.get(url,params={'mode':'json','limit':100},timeout=15,allow_redirects=False)
            response.raise_for_status();data=response.json()
            if not isinstance(data,list):raise ValueError('Expected posting array')
            for j in data:
                category=j.get('categories') or {}; country=j.get('country','')
                rows.append({'title':j.get('text',''),'company':company,'location':category.get('location','')+(', India' if country=='IN' else ''),'job_url':j.get('hostedUrl',''),'description':text(j.get('descriptionPlain') or j.get('description','')),'date_posted':'','site':label,'requisition_id':j.get('id','')})
            health[label]={'status':'response_schema_validated','returned':len(data),'coverage':'first 100 postings requested; not an exhaustive employer check'}
        except Exception as exc:health[label]={'status':'unavailable_or_unvalidated','error_type':type(exc).__name__}
        time.sleep(1)
    health['greenhouse']={'status':'not_configured','reason':'No employer board identifier has been validated yet'}
    health['email_alerts']={'status':'not_configured','reason':'GitHub workflow has not been granted Gmail OAuth access'}
    health['naukri_direct']={'status':'interaction_required','reason':'Existing diagnostic returned recaptcha required; no bypass attempted'}
    enabled=os.getenv('FREE_API_ENABLED')=='1'
    ledger=Path('data/free_api_usage.json');usage=json.loads(ledger.read_text()) if ledger.exists() else {}
    day=datetime.now(timezone.utc).date().isoformat()
    for provider in ['serpapi','adzuna']:
        configured=bool(os.getenv('SERPAPI_API_KEY')) if provider=='serpapi' else bool(os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY'))
        if not enabled or not configured:
            health[provider]={'status':'not_enabled_or_configured'};continue
        slot=day+':'+provider
        if usage.get(slot,0)>=6:health[provider]={'status':'daily_local_request_budget_reached'};continue
        usage[slot]=usage.get(slot,0)+1;ledger.parent.mkdir(parents=True,exist_ok=True);ledger.write_text(json.dumps(usage,indent=2))
        try:
            if provider=='serpapi':
                response=requests.get('https://serpapi.com/search.json',params={'engine':'google_jobs','q':'credit risk senior manager India','gl':'in','api_key':os.environ['SERPAPI_API_KEY']},timeout=20)
                response.raise_for_status();payload=response.json()
                if payload.get('error'):raise ValueError('Provider returned an error')
                for j in payload.get('jobs_results',[]):
                    choices=j.get('apply_options') or [];link=choices[0].get('link','') if choices else j.get('share_link','')
                    rows.append({'title':j.get('title',''),'company':j.get('company_name',''),'location':j.get('location',''),'job_url':link,'description':text(j.get('description','')),'date_posted':(j.get('detected_extensions') or {}).get('posted_at',''),'site':'serpapi_google_jobs'})
            else:
                response=requests.get('https://api.adzuna.com/v1/api/jobs/in/search/1',params={'app_id':os.environ['ADZUNA_APP_ID'],'app_key':os.environ['ADZUNA_APP_KEY'],'what':'credit risk','results_per_page':20,'sort_by':'date'},timeout=20)
                response.raise_for_status();payload=response.json()
                for j in payload.get('results',[]):rows.append({'title':j.get('title',''),'company':(j.get('company') or {}).get('display_name',''),'location':(j.get('location') or {}).get('display_name',''),'job_url':j.get('redirect_url',''),'description':text(j.get('description','')),'date_posted':j.get('created',''),'site':'adzuna','description_is_snippet':True})
            health[provider]={'status':'request_completed','scope':'single query, first page only; local budget is not a provider billing guarantee'}
        except Exception as exc:health[provider]={'status':'request_failed','error_type':type(exc).__name__}
    return rows,health
