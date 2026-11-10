import csv, hashlib, io, json, logging, multiprocessing as mp, os, re, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import scanner as engine
import quality
import freshness
from employer_sources import Client, Paused, employer, structured, RISK

STATE=Path('data/ordered-state.json');PAGE=25;SENIOR=re.compile(r'\b(senior manager|associate director|director|vice president|avp|svp|vp|head of credit|head of risk)\b',re.I)

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def board_worker(source,query,offset,path):
    result={'rows':[],'errors':{},'warnings':{}}
    try:
        from jobspy import scrape_jobs
        frame=scrape_jobs(site_name=[source],search_term=query,location='India',country_indeed='india',hours_old=48,results_wanted=PAGE,offset=offset,fetch_description=False,verbose=1)
        result.update(rows=frame.to_dict('records'),errors=frame.attrs.get('errors',{}),warnings=frame.attrs.get('warnings',{}))
        if source=='linkedin':
            from jobspy.linkedin.constant import max_results
            result['native_cap']=max_results
    except Exception as exc:result['errors']={source:type(exc).__name__}
    Path(path).write_text(json.dumps(result,default=str),encoding='utf-8')

def india(location):return bool(re.search(r'\bIndia\b|(?:^|,\s*)IN(?:$|\s*\()',location,re.I))

def location(value):
    if isinstance(value,dict):return ', '.join(str(value.get(k,'')) for k in ['city','state','country'])
    return engine.clean(value)

def main():
    employers=list(csv.DictReader(io.StringIO(Path('config/employers.csv').read_text(encoding='utf-8'))))
    if len(employers)!=100 or len({e['name'] for e in employers})!=100:raise ValueError('Expected exactly 100 distinct configured targets')
    queries=list(dict.fromkeys(engine.DOMAINS+[e['name']+' credit risk' for e in employers]))
    fingerprint=hashlib.sha256((Path('config/employers.csv').read_text()+Path(__file__).read_text()+Path('employer_sources.py').read_text()+Path('quality.py').read_text()+Path('freshness.py').read_text()).encode()).hexdigest()
    prior=json.loads(STATE.read_text()) if STATE.exists() else {}
    now=datetime.now(timezone.utc)
    if prior.get('fingerprint')==fingerprint and not prior.get('pass_finished'):
        state=prior
    else:state={'fingerprint':fingerprint,'started_at':now.isoformat(),'phase':0,'query_index':0,'offset':0,'employer_index':0,'items':{},'board_coverage':{},'employer_coverage':{},'observations':0,'pass_finished':False}
    deadline=time.monotonic()+150*60
    roots=[e[k] for e in employers for k in ['careers_url','listing_url'] if e.get(k)]+['https://www.linkedin.com/','https://in.indeed.com/']
    client=Client(roots,deadline)
    profile=json.loads(os.getenv('CANDIDATE_PROFILE_JSON') or '{}')
    old=json.loads(Path('site/jobs.json').read_text()) if Path('site/jobs.json').exists() else {'jobs':[]}
    previous={quality.canonical(j.get('job_url','')):j for j in old.get('jobs',[])}
    def checkpoint():save(STATE,state)
    def consume(raw,source):
        job={k:engine.clean(raw.get(k,'')) for k in ['title','company','job_url','description','date_posted','requisition_id','valid_through']};job['location']=location(raw.get('location',''));job['site']=source
        url=quality.canonical(job['job_url'])
        if not url or not job['title']:return
        state['observations']+=1;existing=state['items'].get(url,{})
        stamp=datetime.now(timezone.utc).isoformat();events=existing.get('posting_events',[])
        if job['date_posted']:
            event={'value':job['date_posted'],'url':url,'source':source}
            if event not in events:events.append(event)
        if existing.get('description_available') and not job['description']:
            existing.update(last_seen=stamp,posting_events=events);checkpoint();return
        assessment=quality.assess(job,profile);assessment['gates']['india']=india(job['location'])
        assessment['gates']['seniority']=bool(SENIOR.search(job['title']))
        ready=len(job['description'])>=300
        eligible=all(assessment['gates'].get(k) for k in ['domain','seniority','india']) and ready
        scored=engine.score(dict(job))
        eligible=eligible and scored is not None and not re.search(r'engineering|developer|software|devops|risk tech',job['title'],re.I)
        scored=scored or dict(job,match_score=0,tier='stretch',matched_tags=[])
        scored.update(assessment,eligibility='eligible' if eligible else 'needs_review',id=existing.get('id',previous.get(url,{}).get('id',hashlib.sha256(url.encode()).hexdigest()[:24])),first_seen=existing.get('first_seen',previous.get(url,{}).get('first_seen',stamp)),last_seen=stamp,posting_events=events,description_available=ready,description_excerpt=job['description'][:500],canonical_url=url,availability=raw.get('availability','unverified'))
        scored.pop('description',None);state['items'][url]=scored;checkpoint()
    context=mp.get_context('spawn')
    try:
        for phase,source in enumerate(['linkedin','indeed']):
            if state['phase']>phase:continue
            print('PHASE '+source,flush=True)
            while state['query_index']<len(queries):
                client.guard();q=queries[state['query_index']];key=source+':'+str(state['query_index']);coverage=state['board_coverage'].setdefault(key,{'query':q,'source':source,'state':'pending','windows':0,'observations':0,'seen':[]})
                if state['offset']>=2500:coverage['state']='safety_or_source_cap';state['query_index']+=1;state['offset']=0;checkpoint();continue
                with tempfile.TemporaryDirectory() as tmp:
                    path=str(Path(tmp)/'page.json');process=context.Process(target=board_worker,args=(source,q,state['offset'],path));process.start();process.join(min(90,max(1,deadline-time.monotonic())))
                    if process.is_alive():process.terminate();process.join(3)
                    if process.is_alive():process.kill();process.join()
                    try:page=json.loads(Path(path).read_text())
                    except (OSError,ValueError):page={'rows':[],'errors':{'worker':'failed_or_timed_out'}}
                client.guard();coverage['windows']+=1;rows=page['rows'];coverage['observations']+=len(rows)
                if page.get('errors'):
                    coverage.update(state='source_error',errors=page['errors'])
                    message=json.dumps(page['errors'])
                    if re.search(r'429|rate.limit',message,re.I):raise Paused('Rate limited; saved page cursor will be retried in a later run')
                    if re.search(r'403|401|captcha|access denied',message,re.I):
                        coverage['state']='access_required'
                        for index in range(state['query_index']+1,len(queries)):state['board_coverage'][source+':'+str(index)]={'query':queries[index],'source':source,'state':'not_attempted_source_access_refused','windows':0,'observations':0,'seen':[]}
                        state['query_index']=len(queries)
                    else:state['query_index']+=1
                    state['offset']=0;checkpoint();continue
                if not rows:
                    coverage['state']='empty_terminal_observed' if not page.get('warnings') else 'empty_or_throttled_unverified';state['query_index']+=1;state['offset']=0;checkpoint();continue
                ids={str(j.get('job_url','')) for j in rows};new=ids-set(coverage['seen'])
                for row in rows:consume(row,source)
                coverage['seen']=sorted(set(coverage['seen'])|ids)
                if not new:coverage['state']='pagination_stalled';state['query_index']+=1;state['offset']=0
                else:state['offset']+=PAGE;coverage['state']='paging'
                if page.get('native_cap') and state['offset']>=int(page['native_cap']):coverage['state']='platform_cap';state['query_index']+=1;state['offset']=0
                checkpoint();print(f"{source} query={state['query_index']}/{len(queries)} offset={state['offset']} unique={len(state['items'])}",flush=True);time.sleep(2)
            state.update(phase=phase+1,query_index=0,offset=0);checkpoint()
        print('PHASE employers: sequential traversal',flush=True)
        while state['employer_index']<len(employers):
            client.guard();entry=employers[state['employer_index']]
            print(f"EMPLOYER {state['employer_index']+1}/100 {entry['name']}",flush=True)
            state['employer_coverage'][entry['name']]=employer(entry,client,consume)
            state['employer_index']+=1;checkpoint()
        state['phase']=3;checkpoint()
        print('PHASE description evidence',flush=True)
        for url,item in list(state['items'].items()):
            has_fresh_date=any(freshness.assess({'date_posted':e['value'],'job_url':e['url']})['status']=='within_48h' for e in item.get('posting_events',[]))
            if (item.get('description_available') and has_fresh_date) or item.get('detail_attempted') or not SENIOR.search(item['title']) or not RISK.search(item['title']):continue
            client.guard()
            try:
                response=client.request(url);rows,soup=structured(response.text,url,item.get('company',''))
                if rows:
                    for row in rows:consume(row,item['site'])
                elif 'linkedin.com' in (client.allowed(url)):
                    div=soup.select_one('div.show-more-less-html__markup')
                    if div:consume(dict(item,description=div.get_text(' ',strip=True)),item['site'])
            except Paused:raise
            except Exception as exc:item['detail_error']=type(exc).__name__
            state['items'][url]['detail_attempted']=True;checkpoint()
        state['phase']=4;checkpoint()
    except Paused:
        state['paused_at']=datetime.now(timezone.utc).isoformat();checkpoint();print('PAUSED: checkpoints saved; no new results published',flush=True);return 75
    now=datetime.now(timezone.utc);fresh=[];review=0;fresh_count=0
    for item in state['items'].values():
        verdict=None
        for event in item.get('posting_events',[]):
            result=freshness.assess({'date_posted':event['value'],'job_url':event['url']},now)
            if result['status']=='within_48h':verdict=result;break
        if not verdict:continue
        fresh_count+=1
        if item.get('eligibility')=='eligible':fresh.append(dict(item,freshness=verdict))
        else:review+=1
    fresh.sort(key=lambda j:-j['match_score'])
    board_gaps=sum(c['state']!='empty_terminal_observed' for c in state['board_coverage'].values())
    employer_gaps=sum(c['state']!='exhausted_accessible_listing' for c in state['employer_coverage'].values())
    coverage={'ordered_phases':['linkedin','indeed','employers','description_evidence','publication'],'employers_configured':100,'employer_entries_attempted':state['employer_index'],'employer_listing_scans_with_gaps':employer_gaps,'board_queries_with_gaps':board_gaps,'board_searches':state['board_coverage'],'employers':state['employer_coverage'],'coverage_complete':False,'note':'Overall coverage remains unverified even when every attempt finishes. A terminal empty response is an observation, not proof of full market coverage. Failed, unsupported and capped sources are not treated as zero vacancies.'}
    report={'last_scan':now.isoformat(),'status':'completed_with_coverage_gaps' if board_gaps or employer_gaps else 'completed_attempt_pass','run_id':os.getenv('GITHUB_RUN_ID','local'),'query_count':len(queries),'total_scanned':state['observations'],'actionable':len(fresh),'jobs':fresh,'sources':{'ordered_employer_scan':coverage},'funnel':{'unique_discovered':len(state['items']),'unique_with_adequate_descriptions':sum(j.get('description_available',False) for j in state['items'].values()),'freshness_qualified':fresh_count,'fresh_rule_eligible':len(fresh),'fresh_needs_review':review,'availability_verified':0},'freshness_policy':{'policy':'0_to_48_hours_only','evaluated_at':now.isoformat(),'cutoff':(now-timedelta(hours=48)).isoformat()},'coverage_scope':'All configured phases were attempted in order; see explicit source gaps. No new shortlist was published before the attempt pass finished.','note':'Keyword and title rules are not personalized resume matching. Availability remains unverified unless independently established.'}
    save(Path('site/jobs.json'),report);save(Path('site/coverage.json'),coverage);save(Path('site/scan-status.json'),{'status':report['status'],'run_id':report['run_id'],'updated_at':now.isoformat(),'jobs_found':len(fresh),'coverage_complete':coverage['coverage_complete']})
    Path('site/digest.md').write_text('# Final strict 0–48-hour rule-qualified candidates\n\n'+'\n'.join('- '+j['title']+' | '+j.get('company','')+' | '+j['job_url'] for j in fresh[:30]),encoding='utf-8')
    state['pass_finished']=True;checkpoint()
    print(f'FINAL attempt pass finished: {len(fresh)} fresh rule-qualified candidates; coverage gaps={board_gaps+employer_gaps}',flush=True)
    return 0
if __name__=='__main__':sys.exit(main())
