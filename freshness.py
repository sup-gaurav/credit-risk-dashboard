import json, re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

UTC=timezone.utc

def interval(value, now):
    raw=str(value or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):
        try:day=datetime.fromisoformat(raw).replace(tzinfo=UTC)
        except ValueError:return None
        earliest=day-timedelta(hours=14)
        latest=min(day+timedelta(hours=36),now)
        return (earliest,latest,'conservative_date_only_interval') if earliest<=latest else None
    try:stamp=datetime.fromisoformat(raw.replace('Z','+00:00'))
    except ValueError:return None
    if stamp.tzinfo is None:return None
    stamp=stamp.astimezone(UTC)
    return (stamp,stamp,'source_timestamp') if stamp<=now else None

def assess(job,now=None):
    now=now or datetime.now(UTC);cutoff=now-timedelta(hours=48)
    events=[('posted',job.get('date_posted'))]
    if job.get('repost_evidence_url') and job.get('source_reposted_at'):
        events.append(('reposted',job['source_reposted_at']))
    verdicts=[]
    for kind,value in events:
        bounds=interval(value,now)
        if bounds is None:continue
        low,high,basis=bounds
        if low>=cutoff and high<=now:
            return {'status':'within_48h','event':kind,'basis':basis,'evidence_value':str(value),'evidence_url':job.get('repost_evidence_url') if kind=='reposted' else job.get('job_url',''),'earliest_possible_at':low.isoformat(),'latest_possible_at':high.isoformat(),'expires_at':(low+timedelta(hours=48)).isoformat()}
        verdicts.append('older_than_48h' if high<cutoff else 'boundary_unverified')
    status='boundary_unverified' if 'boundary_unverified' in verdicts else 'older_than_48h' if verdicts else 'date_unverified'
    return {'status':status,'reason':'Discovery time, last_seen and synthetic posted_at are not posting/reposting evidence'}

def apply():
    now=datetime.now(UTC);path=Path('site/jobs.json')
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'jobs':[],'last_scan':None,'status':'awaiting_first_scan'}
    archive_path=Path('data/jobs_archive.json');archive_path.parent.mkdir(parents=True,exist_ok=True)
    history=json.loads(archive_path.read_text(encoding='utf-8')) if archive_path.exists() else []
    combined={str(j.get('id') or j.get('job_url')):j for j in history+data.get('jobs',[])}
    archive=list(combined.values());counts=Counter();fresh=[]
    for job in archive:
        verdict=assess(job,now);counts[verdict['status']]+=1
        if verdict['status']=='within_48h':fresh.append(dict(job,freshness=verdict))
    fresh.sort(key=lambda j:-int(j.get('match_score',0)))
    archive_path.write_text(json.dumps(archive,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'policy':'0_to_48_hours_only','evaluated_at':now.isoformat(),'cutoff':(now-timedelta(hours=48)).isoformat(),'counts':dict(counts),'date_only_policy':'Unknown timezone is conservatively bounded from UTC+14 to UTC-12; boundary cases are held, never guessed fresh','reposting_policy':'Requires source_reposted_at and a repost_evidence_url; rediscovery alone is not a repost'}
    data.update(jobs=fresh,actionable=len(fresh),freshness_policy=report)
    data['funnel']=dict(data.get('funnel',{}),unique_retained=len(fresh),eligible=sum(j.get('eligibility')=='eligible' for j in fresh),needs_review=sum(j.get('eligibility')!='eligible' for j in fresh))
    Path('site').mkdir(exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    Path('site/freshness_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    Path('site/digest.md').write_text('# Strict 0–48-hour leads\n\nNot a verified-active or personalized shortlist.\n\n'+'\n'.join('- '+j['title']+' | '+j.get('company','')+' | '+j['job_url'] for j in fresh[:30])+'\n',encoding='utf-8')
    print(json.dumps({'freshness_filter_applied':dict(counts),'visible':len(fresh)}),flush=True)
if __name__=='__main__':apply()
