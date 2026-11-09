import hashlib, json, logging, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import runner
import scanner as engine
import quality
from free_adapters import supplements

ORIGINAL_WORKER=runner.task_worker
ORIGINAL_SCORE=engine.score

def normalize(job):
    job=dict(job);location=str(job.get('location',''))
    if re.search(r'(?:^|,\s*)IN$',location):job['location']=location+' (India)'
    return job

def durable_prepare(rows,previous=None,profile=None):
    previous=previous or {}; merged={}
    for row in rows:
        row=normalize(row);url=quality.canonical(str(row.get('job_url','')))
        if not url:continue
        if row.get('eligibility') and not row.get('description'):
            existing=dict(row)
            existing['gates']=dict(existing.get('gates',{}))
            if not existing.get('indirect') and 'India' in row.get('location',''):
                existing['gates']['india']=True
                existing['gaps']=[g for g in existing.get('gaps',[]) if g!='India work location/eligibility needs verification']
                if all(existing['gates'].get(k) for k in ['domain','seniority','india']):existing['eligibility']='eligible'
            candidate=existing
        else:
            candidates=quality.prepare([row],previous,profile)
            if not candidates:continue
            candidate=candidates[0]
        old=merged.get(url)
        if old:
            sources=sorted(set(old.get('sources',[])+candidate.get('sources',[candidate.get('site','unknown')])))
            links=sorted(set(old.get('source_urls',[url])+candidate.get('source_urls',[url])))
            if old.get('description_available') and not candidate.get('description_available'):
                old['last_seen']=max(old.get('last_seen',''),candidate.get('last_seen',''));old['sources']=sources;old['source_urls']=links
                continue
            candidate.update(id=old.get('id',candidate.get('id')),first_seen=old.get('first_seen',candidate.get('first_seen')),sources=sources,source_urls=links,legacy_ids=sorted(set(old.get('legacy_ids',[])+candidate.get('legacy_ids',[]))))
        merged[url]=candidate
    return sorted(merged.values(),key=lambda j:(j.get('eligibility')!='eligible',-int(j.get('match_score',0)),j.get('title','')))

def discovery_worker(task,path):
    if task['source']!='linkedin':return ORIGINAL_WORKER(task,path)
    rows,states=[],[]
    try:
        from jobspy import scrape_jobs
        errors=[]
        class Capture(logging.Handler):
            def emit(self,record):
                if record.levelno>=logging.ERROR:errors.append(record.getMessage())
        handler=Capture();logging.getLogger().addHandler(handler)
        for name,logger in list(logging.Logger.manager.loggerDict.items()):
            if name.lower().startswith('jobspy') and isinstance(logger,logging.Logger):logger.addHandler(handler)
        frame=scrape_jobs(site_name=['linkedin'],search_term=task['query'],location='India',results_wanted=10,hours_old=168,country_indeed='india',linkedin_fetch_description=False)
        rows=[] if frame is None else frame.to_dict('records')
        stamp=datetime.now(timezone.utc).isoformat();saved=[]
        for row in rows:
            row['site']='linkedin'
            saved.append({**{k:engine.clean(row.get(k,'')) for k in ['title','company','location','job_url','date_posted']},'discovered_at':stamp,'detail_state':'pending'})
        directory=Path('data/discovery');directory.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(task['query'].encode()).hexdigest()[:20]
        target=directory/(key+'.json')
        prior=json.loads(target.read_text()) if target.exists() else []
        unique={j['job_url']:j for j in prior+saved if j.get('job_url')}
        target.write_text(json.dumps(list(unique.values()),indent=2),encoding='utf-8')
        states=[{'source':'linkedin','ok':not errors,'returned':len(rows),'error':'; '.join(dict.fromkeys(errors))[:300]}]
    except Exception as exc:states=[{'source':'linkedin','ok':False,'error':str(exc)[:300]}]
    Path(path).write_text(json.dumps({'rows':rows,'states':states},default=str),encoding='utf-8')

def main():
    ancillary='--ancillary' in sys.argv
    if ancillary:sys.argv.remove('--ancillary')
    prior=json.loads(engine.DATA.read_text()) if engine.DATA.exists() else {'jobs':[]}
    company=engine.QUERIES[:72];domain=engine.QUERIES[72:];queries=[]
    for i in range(max(len(company),len(domain))):
        if i<len(domain):queries.append(domain[i])
        if i<len(company):queries.append(company[i])
    engine.QUERIES=queries
    if prior.get('query_plan_version')!='free-first-1':prior['query_cursor']=0
    health=prior.get('supplemental_sources',{})
    if ancillary:
        leads,health=supplements();stamp=datetime.now(timezone.utc).isoformat();scored=[]
        Path('data').mkdir(exist_ok=True)
        Path('data/supplemental_leads.json').write_text(json.dumps([{k:engine.clean(j.get(k,'')) for k in ['title','company','location','job_url','date_posted','site','requisition_id']} for j in leads],indent=2),encoding='utf-8')
        for lead in leads:
            lead=normalize(lead);score=ORIGINAL_SCORE(lead)
            if score is not None:score['last_seen']=stamp;scored.append(score)
        prior['jobs']=durable_prepare(prior.get('jobs',[])+scored,prior)
    prior['query_plan_version']='free-first-1';engine.DATA.parent.mkdir(parents=True,exist_ok=True);engine.DATA.write_text(json.dumps(prior,indent=2),encoding='utf-8')
    runner.task_worker=discovery_worker;runner.prepare=durable_prepare
    engine.score=lambda row:ORIGINAL_SCORE(normalize(row))
    runner.main()
    data=json.loads(engine.DATA.read_text());data['query_plan_version']='free-first-1';data['supplemental_sources']=health;data.setdefault('sources',{}).update(health)
    data['description_queue']={'pending_unique_urls':len({j['job_url'] for p in Path('data/discovery').glob('*.json') for j in json.loads(p.read_text()) if j.get('job_url')}),'state':'saved_discovery_metadata_only; separate description retrieval is not enabled yet'}
    data['coverage_scope']='One discovery page per selected query; not full pagination or exhaustive coverage. Naukri CAPTCHA endpoint and Google News RSS are not requested by this entry point.'
    engine.DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
