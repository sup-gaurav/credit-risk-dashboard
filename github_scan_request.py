import json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

WORKFLOW='dashboard.yml'
ACTIVE={'queued','in_progress','waiting','pending','requested'}

def request_id(event):
    owner=event.get('repository',{}).get('owner',{}).get('login')
    issue=event.get('issue',{})
    if not owner or issue.get('user',{}).get('login')!=owner:return None
    match=re.fullmatch(r'\[SCAN\] ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',issue.get('title',''))
    return match.group(1) if match else None

def dispatch_allowed(runs,now=None):
    now=now or datetime.now(timezone.utc)
    if any(r.get('status') in ACTIVE for r in runs):return False,'Another scan is active; use its GitHub Actions page.'
    if runs:
        try:
            created=datetime.fromisoformat(runs[0]['created_at'].replace('Z','+00:00'))
            if (now-created).total_seconds()<300:return False,'Five-minute cooldown: no new scan was dispatched.'
        except (KeyError,ValueError):return False,'Cannot verify cooldown; no scan was dispatched.'
    return True,'Request accepted'

def main():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    correlation=request_id(event)
    if correlation is None:print('Ignored: scan requests require the repository owner and a valid request title.');return
    repo=os.environ['GITHUB_REPOSITORY'];token=os.environ['GH_TOKEN'];number=int(event['issue']['number'])
    def api(method,path,payload=None):
        request=Request('https://api.github.com/repos/'+repo+path,data=json.dumps(payload).encode() if payload is not None else None,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'credit-risk-scan-request','Content-Type':'application/json'})
        with urlopen(request,timeout=20) as response:
            body=response.read();return json.loads(body) if body else None
    runs=api('GET','/actions/workflows/'+WORKFLOW+'/runs?branch=main&per_page=30').get('workflow_runs',[])
    allowed,message=dispatch_allowed(runs)
    workflow_url='https://github.com/'+repo+'/actions/workflows/'+WORKFLOW
    if allowed:
        api('POST','/actions/workflows/'+WORKFLOW+'/dispatches',{'ref':'main','inputs':{'requested_by':'dashboard','request_id':correlation}})
        message='Dispatch request accepted; this is not confirmation that execution has started. Find the run named `Credit Risk Scan '+correlation+'`. The dashboard can monitor this request. Strict 0–48-hour visibility remains enforced.'
    api('POST','/issues/'+str(number)+'/comments',{'body':message+'\n\n[Open GitHub Actions]('+workflow_url+')'})
    print(json.dumps({'request_id':correlation,'dispatch_accepted':allowed}),flush=True)
if __name__=='__main__':main()
