import ast, hashlib, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

MARKER='# source-recovery-v1'

def defer_source(state,source,phase,queries,now=None):
    now=now or datetime.now(timezone.utc)
    record={'phase':phase,'query_index':state['query_index'],'offset':state['offset'],'retry_not_before':(now+timedelta(hours=1)).isoformat(),'reason':'HTTP 429; source deferred without blocking other sources'}
    state.setdefault('deferred_boards',{})[source]=record
    for index in range(state['query_index'],len(queries)):
        key=source+':'+str(index)
        coverage=state.setdefault('board_coverage',{}).setdefault(key,{'query':queries[index],'source':source,'windows':0,'observations':0,'seen':[]})
        coverage['state']='deferred_rate_limit';coverage['retry_not_before']=record['retry_not_before']
    state['query_index']=len(queries);state['offset']=0
    print('DEFERRED '+source+' until '+record['retry_not_before']+'; continuing independent sources',flush=True)

def mark_deferred(state,source,queries):
    record=state.get('deferred_boards',{}).get(source)
    if not record:return
    for index in range(state['query_index'],len(queries)):
        key=source+':'+str(index)
        coverage=state.setdefault('board_coverage',{}).setdefault(key,{'query':queries[index],'source':source,'windows':0,'observations':0,'seen':[]})
        coverage.update(state='deferred_rate_limit',retry_not_before=record['retry_not_before'])

def ready(state,source,now=None):
    record=state.get('deferred_boards',{}).get(source)
    if record:
        now=now or datetime.now(timezone.utc)
        return datetime.fromisoformat(record['retry_not_before'])<=now
    return source not in state.get('completed_boards',[])

def advance(state,phase):
    next_source='indeed' if phase==0 else None
    resume=state.get('deferred_boards',{}).get(next_source,{})
    state.update(phase=phase+1,query_index=resume.get('query_index',0),offset=resume.get('offset',0))

def finish(state):
    pending=state.get('deferred_boards',{})
    if pending:
        record=min(pending.values(),key=lambda r:r['phase'])
        state.update(phase=record['phase'],query_index=record['query_index'],offset=record['offset'],pass_finished=False)
    else:state['pass_finished']=True

def transform(code):
    if code.startswith(MARKER):return code
    changes=[
      ("+Path('freshness.py').read_text()).encode()", "+Path('freshness.py').read_text()+Path('scan_recovery.py').read_text()).encode()"),
      ("            if state['phase']>phase:continue\n            print('PHASE '+source,flush=True)", "            if state['phase']>phase:continue\n            if not recovery_ready(state,source):\n                mark_deferred(state,source,queries)\n                advance_source(state,phase);checkpoint();continue\n            source_deferred=False\n            print('PHASE '+source,flush=True)"),
      ("                    if re.search(r'429|rate.limit',message,re.I):raise Paused('Rate limited; saved page cursor will be retried in a later run')", "                    if re.search(r'429|rate.limit',message,re.I):\n                        defer_source(state,source,phase,queries);source_deferred=True;checkpoint();continue"),
      ("            state.update(phase=phase+1,query_index=0,offset=0);checkpoint()", "            if not source_deferred:\n                state.setdefault('deferred_boards',{}).pop(source,None)\n                if source not in state.setdefault('completed_boards',[]):state['completed_boards'].append(source)\n            advance_source(state,phase);checkpoint()"),
      ("    save(Path('site/jobs.json'),report);", "    report['campaign_started_at']=state.get('started_at')\n    report['deferred_sources']=state.get('deferred_boards',{})\n    if report['deferred_sources']:report['status']='completed_with_deferred_sources'\n    save(Path('site/jobs.json'),report);"),
      ("    state['pass_finished']=True;checkpoint()", "    finish_recovery(state);checkpoint()")
    ]
    for before,after in changes:
        if code.count(before)!=1:raise ValueError('Unexpected coordinator layout; migration stopped safely')
        code=code.replace(before,after,1)
    code=MARKER+'\nfrom scan_recovery import defer_source, mark_deferred, ready as recovery_ready, advance as advance_source, finish as finish_recovery\n'+code
    ast.parse(code);return code

def fingerprint(code,include_recovery=False):
    text=Path('config/employers.csv').read_text()+code+Path('employer_sources.py').read_text()+Path('quality.py').read_text()+Path('freshness.py').read_text()
    if include_recovery:text+=Path('scan_recovery.py').read_text()
    return hashlib.sha256(text.encode()).hexdigest()

def migrate():
    path=Path('ordered_scan.py');before=path.read_text();after=transform(before)
    if after==before:print('Recovery migration already installed');return
    state_path=Path('data/ordered-state.json');state=json.loads(state_path.read_text()) if state_path.exists() else None
    if state and state.get('fingerprint')!=fingerprint(before):raise ValueError('Checkpoint fingerprint mismatch; no code or checkpoint modified')
    if state:
        phase=state.get('phase',4)
        if phase in (0,1):
            source=['linkedin','indeed'][phase];coverage=state.get('board_coverage',{}).get(source+':'+str(state.get('query_index',0)),{})
            if re.search(r'429|rate.limit',json.dumps(coverage.get('errors',{})),re.I):
                anchor=datetime.fromisoformat(state.get('paused_at') or datetime.now(timezone.utc).isoformat())
                state.setdefault('deferred_boards',{})[source]={'phase':phase,'query_index':state['query_index'],'offset':state['offset'],'retry_not_before':(anchor+timedelta(hours=1)).isoformat(),'reason':'Recovered existing throttled checkpoint'}
        state['fingerprint']=fingerprint(after,True);state['recovery_migration']='v1'
    path.write_text(after)
    if state:
        temp=state_path.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2));temp.replace(state_path)
    print(json.dumps({'recovery_installed':True,'checkpoint_items_preserved':len(state.get('items',{})) if state else 0,'checkpoint_offset_preserved':state.get('offset') if state else None}),flush=True)
if __name__=='__main__':migrate()
