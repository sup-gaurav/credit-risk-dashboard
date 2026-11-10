import argparse, hashlib, json, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import freshness

def prepare(phase,outcome='pending'):
    now=datetime.now(timezone.utc);path=Path('site/jobs.json')
    data=json.loads(path.read_text()) if path.exists() else {'jobs':[],'last_scan':None,'status':'awaiting_first_scan'}
    fresh=[]
    for job in data.get('jobs',[]):
        verdict=freshness.assess(job,now)
        for event in job.get('posting_events',[]):
            candidate=freshness.assess({'date_posted':event.get('value'),'job_url':event.get('url','')},now)
            if candidate['status']=='within_48h':verdict=candidate;break
        if verdict['status']=='within_48h' and job.get('eligibility')=='eligible':fresh.append(dict(job,freshness=verdict))
    data.update(jobs=fresh,actionable=len(fresh));data.setdefault('freshness_policy',{}).update(policy='0_to_48_hours_only',evaluated_at=now.isoformat(),cutoff=(now-timedelta(hours=48)).isoformat())
    path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    state_path=Path('data/ordered-state.json');state=json.loads(state_path.read_text()) if state_path.exists() else {}
    run=os.getenv('GITHUB_RUN_ID','local');attempt=os.getenv('GITHUB_RUN_ATTEMPT','1');build=run+'-'+attempt+'-'+phase
    metadata={'build_id':build,'phase':phase,'scan_outcome':outcome,'built_at':now.isoformat(),'workflow_commit':os.getenv('GITHUB_SHA','local'),'execution_run_id':run,'results_run_id':data.get('run_id'),'results_last_scan':data.get('last_scan'),'visible_candidates':len(fresh),'deferred_sources':state.get('deferred_boards',{}),'note':'App deployment and scan-result completion are separate. A refreshed build does not certify complete source coverage.'}
    Path('site/deployment.json').write_text(json.dumps(metadata,indent=2))
    index=Path('site/index.html');html=index.read_text()
    if '</html>' not in html:raise ValueError('Dashboard closing tag missing; refusing incomplete bootstrap')
    html=re.sub(r'<!-- deployment-bootstrap:start -->.*?<!-- deployment-bootstrap:end -->','',html,flags=re.S)
    html=re.sub(r'<script src="github-scan\.js(?:\?[^"]*)?"></script>','<script src="github-scan.js?build='+quote(build,safe='')+'"></script>',html)
    tag='<!-- deployment-bootstrap:start --><script>window.__DASHBOARD_BUILD__='+json.dumps(build)+';</script><script src="deployment-refresh.js?build='+quote(build,safe='')+'"></script><!-- deployment-bootstrap:end -->'
    html=html.replace('</html>',tag+'\n</html>');index.write_text(html)
    print(json.dumps({'prepared_build':build,'phase':phase,'scan_outcome':outcome,'visible_candidates':len(fresh)}),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['app','outcome'],required=True);parser.add_argument('--outcome',default='pending');args=parser.parse_args();prepare(args.phase,args.outcome)
