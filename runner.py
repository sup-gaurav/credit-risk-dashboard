import argparse, hashlib, json, logging, multiprocessing as mp, os, re, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import scanner as engine
from quality import prepare, digest

def task_worker(task,path):
    rows,states=[],[]
    try:
        source=task['source']
        if source in ['linkedin','indeed']:
            from jobspy import scrape_jobs
            errors=[]
            class Capture(logging.Handler):
                def emit(self,r):
                    if r.levelno>=logging.ERROR: errors.append(r.getMessage())
            handler=Capture(); logging.getLogger().addHandler(handler)
            for name,logger in list(logging.Logger.manager.loggerDict.items()):
                if name.lower().startswith('jobspy') and isinstance(logger,logging.Logger): logger.addHandler(handler)
            frame=scrape_jobs(site_name=[source],search_term=task['query'],location='India',results_wanted=50,hours_old=168,country_indeed='india',linkedin_fetch_description=True)
            rows=[] if frame is None else frame.to_dict('records')
            for row in rows: row['site']=source
            states=[{'source':source,'ok':not errors,'returned':len(rows),'error':'; '.join(dict.fromkeys(errors))[:300]}]
        else: rows,states=getattr(engine,source)()
    except Exception as exc: states=[{'source':task['source'],'ok':False,'error':str(exc)[:300]}]
    Path(path).write_text(json.dumps({'rows':rows,'states':states},default=str),encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--count',type=int,default=4);p.add_argument('--budget',type=int,default=240);p.add_argument('--ancillary',action='store_true');a=p.parse_args()
    if not 1<=a.count<=len(engine.QUERIES) or a.budget<1:p.error('Invalid count or budget')
    prior=json.loads(engine.DATA.read_text(encoding='utf-8')) if engine.DATA.exists() else {'jobs':[]}
    run=os.getenv('GITHUB_RUN_ID','local'); same=prior.get('run_id')==run
    sources=prior.get('sources',{}) if same else {}
    disabled=prior.get('disabled_sources',{}) if same else {}
    disabled['glassdoor']='Disabled after repeated 403 responses'
    sources['glassdoor']={'disabled':True,'reason':disabled['glassdoor']}
    cursor=int(prior.get('query_cursor',0))%len(engine.QUERIES)
    selected=[(cursor+i)%len(engine.QUERIES) for i in range(a.count)]
    pending=[{'source':s,'query':engine.QUERIES[q],'q':q} for q in selected for s in ['linkedin','indeed']]
    if a.ancillary:pending += [{'source':s,'q':None} for s in ['rss','naukri']]
    raw=int(prior.get('total_scanned',0)) if same else 0
    screened=int(prior.get('descriptions_screened_observations',0)) if same else 0
    observations=[]; completed=set();active={}; deadline=time.monotonic()+a.budget
    profile=json.loads(os.getenv('CANDIDATE_PROFILE_JSON') or '{}')
    retained=[]
    for j in prior.get('jobs',[]):
        try:
            if datetime.fromisoformat(j['last_seen'])>=datetime.now(timezone.utc)-timedelta(days=14):retained.append(j)
        except (ValueError,KeyError):pass
    def checkpoint(status):
        rows=retained+observations
        jobs=prepare(rows,prior,profile)[:3000]
        nextq=next((q for q in selected if any((q,s) not in completed for s in ['linkedin','indeed'])),(cursor+len(selected))%len(engine.QUERIES))
        stamp=datetime.now(timezone.utc).isoformat()
        data={'last_scan':stamp,'checkpoint_at':stamp,'status':status,'run_id':run,'total_scanned':raw,'descriptions_screened_observations':screened,'actionable':len(jobs),'query_count':len(engine.QUERIES),'selected_queries':len(selected),'completed_query_source_tasks':len(completed),'query_cursor':nextq,'sources':sources,'disabled_sources':disabled,'funnel':{'raw_observations_this_run':raw,'unique_retained':len(jobs),'eligible':sum(j['eligibility']=='eligible' for j in jobs),'needs_review':sum(j['eligibility']=='needs_review' for j in jobs),'availability_verified':sum(j['availability']=='active' for j in jobs)},'jobs':jobs,'note':'Checkpoint time is not publication time. Descriptions-screened counts observations, not unique verified screenings. No live listing verifier is enabled. Posting dates are source-reported. Coverage is partial and best-effort.'}
        engine.DATA.parent.mkdir(parents=True,exist_ok=True)
        temp=engine.DATA.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(engine.DATA)
        Path('site/digest.md').write_text(digest(jobs),encoding='utf-8')
    def consume(task,payload):
        nonlocal raw,screened
        stamp=datetime.now(timezone.utc).isoformat(); rows=payload.get('rows',[]);raw+=len(rows)
        for row in rows:
            job={k:engine.clean(row.get(k,'')) for k in ['title','company','location','job_url','description','date_posted','site']}
            job['indirect']=bool(row.get('indirect',False));job['last_seen']=stamp
            if not engine.valid_url(job['job_url']):continue
            if job['description']:screened+=1
            scored=engine.score(dict(job))
            if scored is not None:observations.append(scored)
        for state in payload.get('states',[]):
            s=state['source'];stats=sources.setdefault(s,{'requests_ok':0,'requests_failed':0,'raw_results':0,'errors':[]})
            stats['requests_ok' if state.get('ok') else 'requests_failed']+=1;stats['raw_results']+=state.get('returned',0)
            if not state.get('ok'):
                error=state.get('error','Unknown source error')[:300]
                if error not in stats['errors']:stats['errors']=(stats['errors']+[error])[:4]
                if re.search(r'\b403\b|\b429\b|forbidden|access denied',error,re.I) or stats['requests_failed']>=2:disabled[s]=error;stats.update(disabled=True,reason=error)
        if task['q'] is not None:completed.add((task['q'],task['source']))
        checkpoint('scan_in_progress');print(f"PROGRESS {len(completed)}/{len(selected)*2} tasks; raw={raw}; source={task['source']}; returned={len(rows)}",flush=True)
    checkpoint('scan_in_progress')
    context=mp.get_context('spawn')
    with tempfile.TemporaryDirectory() as temp:
        serial=0; heartbeat=time.monotonic()
        try:
            while (pending or active) and time.monotonic()<deadline:
                while pending and len(active)<2 and time.monotonic()<deadline:
                    task=pending.pop(0)
                    if task['source'] in disabled:
                        if task['q'] is not None:completed.add((task['q'],task['source']))
                        continue
                    serial+=1;path=str(Path(temp)/f'{serial}.json');process=context.Process(target=task_worker,args=(task,path));process.start();active[serial]=(process,task,path,time.monotonic())
                for key,(process,task,path,start) in list(active.items()):
                    limit=60 if task['source'] in ['linkedin','indeed'] else 90
                    if process.is_alive() and time.monotonic()-start<limit:continue
                    if process.is_alive():process.terminate();process.join(3)
                    if process.is_alive():process.kill()
                    process.join()
                    try:payload=json.loads(Path(path).read_text(encoding='utf-8'))
                    except (OSError,ValueError):payload={'rows':[],'states':[{'source':task['source'],'ok':False,'error':f'Worker failed or exceeded {limit}s'}]}
                    consume(task,payload);del active[key]
                if time.monotonic()-heartbeat>=20:print(f'HEARTBEAT active={len(active)} queued={len(pending)} budget_left={max(0,int(deadline-time.monotonic()))}s',flush=True);heartbeat=time.monotonic()
                time.sleep(.2)
        finally:
            for process,task,path,start in active.values():
                if process.is_alive():process.terminate();process.join(3)
                if process.is_alive():process.kill();process.join()
            partial=bool(pending or active)
            errors=any(s.get('requests_failed',0) for s in sources.values())
            checkpoint('partial_budget_reached' if partial else 'batch_completed_with_source_errors' if errors else 'batch_completed')
    print('CHECKPOINT SAVED; ready to publish',flush=True)
if __name__=='__main__':main()
