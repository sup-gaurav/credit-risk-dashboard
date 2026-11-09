import json, re, time, html, hashlib, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote
import xml.etree.ElementTree as ET
import requests

DATA = Path('site/jobs.json')
COMPANIES = "Citi|Goldman Sachs|JPMorgan|Deutsche Bank|Barclays|Morgan Stanley|UBS|Nomura|BNP Paribas|Societe Generale|Macquarie Group|Credit Agricole|Credit Suisse|DBS Bank|Wells Fargo|Standard Chartered|HSBC|Bank of America|MUFG|State Street|BNY Mellon|Northern Trust|PNC Financial|US Bank|KeyBank|Citizens Financial|Fifth Third Bank|Discover Financial|Lloyds Banking Group|BMO Financial|American Express|BlackRock|Oaktree Capital|Ares Management|Fidelity Investments|Apex Group|Moody's|Fitch Ratings|S&P Global|Experian|Equifax|TransUnion|MSCI|Kroll|EY|Deloitte|KPMG|PwC|Accenture|Capgemini|Cognizant|Evalueserve|EXL|SG Analytics|Tiger Analytics|Acuity Analytics|ZS Associates|Capco|PayU|ICICI Bank|Credit Saison|NatWest|OakNorth Bank|Jefferies|SBI Card|HDFC Bank|Kotak Mahindra|Acies|BDO India|Risk Solutions|State Street India|Barclays India".split('|')
DOMAINS = 'credit risk|credit risk analytics|portfolio risk|model validation|model risk|credit scorecard|internal rating|PD LGD EAD|IFRS 9|expected credit loss|delinquency|vintage analysis|roll rate|early warning credit|collections strategy|credit policy|underwriting credit|credit strategy|Basel credit|regulatory capital|stress testing credit|SAS credit risk|commercial lending risk|wholesale credit risk'.split('|')
QUERIES = [f'{c} credit risk India' for c in COMPANIES] + [f'{d} {level} India' for d in DOMAINS for level in ['Senior Manager', 'Vice President Director AVP']]
SENIOR = 'senior manager|associate director|director|vice president|vp|avp|assistant vice president|deputy vice president|dvp|svp|lead analyst|principal analyst|head of credit|head of risk|cro'.split('|')
EXCLUDE = 'intern|fresher|trainee|apprentice|teller|software engineer|java developer|devops|data entry|receptionist|payroll|procurement|supply chain|marketing manager|hr manager'.split('|')
GROUPS = [
    ('Credit risk', 20, 'credit risk|portfolio risk|credit portfolio|risk analytics|credit analytics'),
    ('Models', 18, 'pd model|probability of default|lgd|loss given default|ead|exposure at default|model development|model monitoring|model validation|model risk|scorecard|credit scoring|internal rating|irb'),
    ('Regulatory', 18, 'ifrs 9|ifrs9|ecl|expected credit loss|basel|ccar|cecl|icaap|regulatory capital|rwa|stress testing|provisioning'),
    ('Portfolio', 14, 'vintage analysis|roll rate|roll-rate|migration matrix|delinquency|dpd|portfolio monitoring|early warning|collections|loss forecasting|portfolio analytics'),
    ('Policy', 14, 'credit policy|underwriting|credit origination|loan origination|credit strategy'),
    ('Lending', 14, 'commercial lending|sme|msme|business loans|commercial credit|wholesale credit|corporate credit|nbfc|retail credit|consumer credit'),
    ('Governance', 10, 'risk governance|regulatory reporting|second line|independent review|model audit|risk framework|risk appetite')
]

def clean(value):
    if value is None: return ''
    s = str(value)
    return '' if s.lower() in ('nan', 'nat', 'none', '<na>') else html.unescape(re.sub('<[^>]+>', ' ', s)).strip()

def has(text, word):
    return re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', text, re.I) is not None

def valid_url(url):
    try:
        p = urlparse(url)
        return p.scheme in ('https', 'http') and bool(p.netloc)
    except ValueError: return False

def score(job):
    title = job['title'].lower()
    text = title + ' ' + job.get('description', '').lower()
    if any(has(title, w) for w in EXCLUDE): return None
    if not any(has(text, w) for w in GROUPS[0][2].split('|')): return None
    points, tags = 0, []
    if any(has(title, w) for w in SENIOR): points += 25; tags.append('Seniority')
    else: points -= 20
    if has(title, 'credit risk') or has(title, 'portfolio risk'): points += 20
    for label, weight, keywords in GROUPS:
        if any(has(text, w) for w in keywords.split('|')): points += weight; tags.append(label)
    for skill, weight in [('sas', 16), ('python', 10), ('sql', 10), ('power bi', 6), ('tableau', 6)]:
        if has(text, skill): points += weight; tags.append(skill.upper())
    loc = job.get('location', '').lower()
    points += max([w for city, w in [('noida',18),('gurugram',18),('gurgaon',18),('delhi',15),('mumbai',10),('bengaluru',10),('bangalore',10),('hyderabad',8),('pune',8),('chennai',8)] if city in loc] or [0])
    if any(has(job.get('company',''), c) for c in COMPANIES): points += 12
    for signal, penalty in [('entry level',-20),('0-2 years',-25),('night shift',-8),('contract',-5),('temporary',-5)]:
        if has(text, signal): points += penalty
    if points < 25: return None
    job.update(match_score=points, tier='hot' if points >= 85 else 'good' if points >= 60 else 'monitor' if points >= 40 else 'stretch', matched_tags=tags)
    job['work_mode'] = 'Hybrid' if has(text, 'hybrid') else 'Remote' if has(text, 'remote') or has(text,'work from home') else ''
    return job

def jobspy_query(query):
    from jobspy import scrape_jobs
    rows, states = [], []
    for site in ['linkedin', 'indeed', 'glassdoor']:
        try:
            df = scrape_jobs(site_name=[site], search_term=query, location='India', results_wanted=100, hours_old=48, country_indeed='india', linkedin_fetch_description=True)
            found = [] if df is None else df.to_dict('records')
            for row in found: row['site'] = site
            rows.extend(found)
            states.append({'source':site,'ok':True,'returned':len(found)})
        except Exception as exc:
            logging.exception('Source failed: %s / %s', site, query)
            states.append({'source':site,'ok':False,'error':str(exc)[:240]})
        time.sleep(1)
    return rows, states

def naukri():
    rows, states = [], []
    for kw in ['credit risk senior manager', 'credit risk associate director', 'credit risk vice president', 'IFRS 9 credit risk', 'model validation credit risk', 'portfolio risk senior manager']:
        try:
            r = requests.get('https://www.naukri.com/jobapi/v3/search', params={'noOfResults':50,'urlType':'search_by_keyword','searchType':'adv','keyword':kw,'pageNo':1,'k':kw,'seoKey':'jobs','src':'jobsearchDesk'}, headers={'User-Agent':'Mozilla/5.0','Systemid':'Naukri','Appid':'109'}, timeout=25)
            r.raise_for_status()
            jobs = r.json().get('jobDetails',[])
            for j in jobs:
                placeholders = j.get('placeholders') or [{}]
                link = j.get('jdURL','')
                rows.append({'title':j.get('title',''),'company':j.get('companyName',''),'location':placeholders[0].get('label',''),'job_url':link if link.startswith('http') else 'https://www.naukri.com'+link,'description':j.get('jobDescription',''),'date_posted':j.get('footerPlaceholderLabel',''),'site':'naukri'})
            states.append({'source':'naukri','ok':True,'returned':len(jobs)})
        except Exception as exc:
            logging.exception('Naukri failed')
            states.append({'source':'naukri','ok':False,'error':str(exc)[:240]})
        time.sleep(1)
    return rows, states

def rss():
    rows, states = [], []
    for domain in ['naukri.com','iimjobs.com','jobs.citi.com','myworkdayjobs.com','in.linkedin.com/jobs/view','foundit.in']:
        try:
            q = f'site:{domain} "credit risk" India when:2d'
            r = requests.get('https://news.google.com/rss/search?q='+quote(q)+'&hl=en-IN&gl=IN&ceid=IN:en', timeout=25)
            r.raise_for_status()
            items = ET.fromstring(r.content).findall('.//item')
            for item in items:
                rows.append({'title':item.findtext('title',''),'company':item.findtext('source','Portal/ATS'),'location':'India','job_url':item.findtext('link',''),'description':item.findtext('description',''),'date_posted':item.findtext('pubDate',''),'site':'rss','indirect':True})
            states.append({'source':'rss','ok':True,'returned':len(items)})
        except Exception as exc:
            logging.exception('RSS failed')
            states.append({'source':'rss','ok':False,'error':str(exc)[:240]})
    return rows, states

def main():
    logging.basicConfig(level=logging.INFO)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    previous = json.loads(DATA.read_text()) if DATA.exists() else {'jobs':[]}
    rows, states = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(jobspy_query,q) for q in QUERIES] + [pool.submit(naukri),pool.submit(rss)]
        for f in as_completed(futures):
            found, status = f.result()
            rows.extend(found); states.extend(status)
    summary = {}
    for state in states:
        x = summary.setdefault(state['source'], {'requests_ok':0,'requests_failed':0,'raw_results':0,'errors':[]})
        x['requests_ok' if state['ok'] else 'requests_failed'] += 1
        x['raw_results'] += state.get('returned',0)
        if not state['ok'] and state['error'] not in x['errors']: x['errors'] = (x['errors']+[state['error']])[:3]
    retained = {}
    for j in previous.get('jobs',[]):
        try:
            if datetime.fromisoformat(j['last_seen']) >= now-timedelta(days=14): retained[j['id']] = j
        except (ValueError, KeyError): pass
    accepted = 0
    for raw in rows:
        job = {k:clean(raw.get(k,'')) for k in ['title','company','location','job_url','description','date_posted','site']}
        if not job['title'] or not valid_url(job['job_url']): continue
        job['indirect'] = bool(raw.get('indirect',False))
        job = score(job)
        if job is None: continue
        key = hashlib.sha256(job['job_url'].encode()).hexdigest()[:24]
        old = retained.get(key,{})
        job.update(id=key,first_seen=old.get('first_seen',stamp),last_seen=stamp)
        job.pop('description',None)
        retained[key] = job
        accepted += 1
    jobs = sorted(retained.values(),key=lambda j:(-j['match_score'],j['title']))[:3000]
    result = {'last_scan':stamp,'status':'completed' if all(x['requests_failed']==0 for x in summary.values()) else 'completed_with_source_errors','total_scanned':len(rows),'accepted_this_scan':accepted,'actionable':len(jobs),'query_count':len(QUERIES),'sources':summary,'jobs':jobs,'note':'Discovery is best-effort. A successful request does not prove complete source coverage. Posting dates are source-reported; some are unknown. Retained results are not checked for closure. RSS links are indirect.'}
    DATA.parent.mkdir(parents=True,exist_ok=True)
    temp = DATA.with_suffix('.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(DATA)
    logging.info('Saved %s jobs from %s raw results',len(jobs),len(rows))

if __name__ == '__main__': main()
