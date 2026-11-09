import hashlib, json, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from email.utils import parsedate_to_datetime

CITIES = 'india|noida|gurgaon|gurugram|delhi|mumbai|bengaluru|bangalore|hyderabad|pune|chennai'.split('|')
SENIOR = r'\b(senior manager|associate director|director|vice president|avp|vp|svp|principal analyst|lead analyst|head of credit|head of risk)\b'
DOMAIN = r'\b(credit risk|credit analytics|portfolio risk|credit portfolio|credit model|credit policy|credit scoring|wholesale credit|commercial credit)\b'

def canonical(url):
    p=urlsplit(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password: return ''
    query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith(('utm_','trk','tracking'))])
    return urlunsplit((p.scheme,p.netloc.lower(),p.path.rstrip('/'),query,''))

def posted(value, now=None):
    now=now or datetime.now(timezone.utc)
    s=str(value or '').strip()
    try: d=datetime.fromisoformat(s.replace('Z','+00:00'))
    except ValueError:
        try: d=parsedate_to_datetime(s)
        except (ValueError,TypeError,IndexError): return None
    if d is None: return None
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    if d>now+timedelta(hours=1): return None
    return d.isoformat()

def assess(row, profile=None):
    profile=profile or {}
    title=str(row.get('title',''))
    description=str(row.get('description',''))
    text=(title+' '+description).lower()
    location=str(row.get('location',''))
    indirect=bool(row.get('indirect'))
    gates={'domain':bool(re.search(DOMAIN,text,re.I)), 'seniority':bool(re.search(SENIOR,title,re.I)), 'india':not indirect and any(re.search(r'\b'+re.escape(c)+r'\b',location,re.I) for c in CITIES)}
    review=[]
    if not gates['seniority']: review.append('Seniority or equivalent scope needs review')
    if not gates['india']: review.append('India work location/eligibility needs verification')
    if not profile: review.append('Candidate resume not supplied; personal fit and mandatory qualifications not assessed')
    keywords=[s for s in ['sas','sql','python','ifrs 9','pd','lgd','ead','model validation','portfolio monitoring','credit policy'] if re.search(r'\b'+re.escape(s)+r'\b',text,re.I)]
    supported=[s for s in keywords if s.casefold() in {str(x).casefold() for x in profile.get('skills',[])}]
    date=posted(row.get('date_posted'))
    eligibility='excluded' if not gates['domain'] else 'eligible' if all(gates.values()) else 'needs_review'
    return {'eligibility':eligibility,'gates':gates,'reasons':keywords,'supported_skill_matches':supported,'gaps':review,'evidence_confidence':'limited' if indirect or not description else 'description_available','posted_at':date,'posted_evidence':str(row.get('date_posted',''))[:100],'availability':'unverified','last_checked':None,'check_note':'No live availability verification performed','fit_assessment':'supported_skill_overlap_only' if profile else 'candidate_profile_missing'}

def prepare(rows, previous=None, profile=None):
    now=datetime.now(timezone.utc).isoformat()
    old={j.get('canonical_url',j.get('job_url','')):j for j in (previous or {}).get('jobs',[])}
    merged={}
    for row in rows:
        url=canonical(str(row.get('job_url','')))
        if not url or not row.get('title'): continue
        job=dict(row)
        assessment=assess(job,profile)
        if assessment['eligibility']=='excluded': continue
        req=str(job.get('requisition_id','')).strip()
        employer=re.sub(r'[^a-z0-9]+',' ',str(job.get('company','')).lower()).strip()
        key=employer+'|req|'+req if employer and req else url
        if key in merged:
            current=merged[key]
            current['source_urls']=sorted(set(current['source_urls']+[url]))
            current['sources']=sorted(set(current['sources']+[str(job.get('site','unknown'))]))
            if str(job.get('last_seen',''))>str(current.get('last_seen','')):
                current.update(last_seen=job.get('last_seen'),date_posted=job.get('date_posted',''),posted_at=assessment['posted_at'])
            continue
        prior=old.get(url,{})
        old_id=hashlib.sha256(str(job.get('job_url','')).encode()).hexdigest()[:24]
        job.update(assessment, id=prior.get('id',hashlib.sha256(key.encode()).hexdigest()[:24]), legacy_ids=sorted(set(prior.get('legacy_ids',[])+[old_id])),canonical_url=url,job_url=url,source_urls=[url],sources=[str(job.get('site','unknown'))],first_seen=prior.get('first_seen',job.get('first_seen',now)),last_seen=job.get('last_seen',now))
        job['description_available']=bool(job.get('description'))
        job['description_excerpt']=str(job.get('description',''))[:500]
        job.pop('description',None)
        merged[key]=job
    groups={}
    for job in merged.values():
        key=tuple(re.sub(r'[^a-z0-9]+',' ',str(job.get(k,'')).lower()).strip() for k in ['company','title','location'])
        groups.setdefault(key,[]).append(job)
    for group in groups.values():
        for job in group: job['possible_duplicate']=len(group)>1
    return sorted(merged.values(),key=lambda j:(j['eligibility']!='eligible',-int(j.get('match_score',0)),j['title']))

def digest(jobs, now=None):
    now=now or datetime.now(timezone.utc)
    selected=[]
    for job in jobs:
        try: first=datetime.fromisoformat(job['first_seen'])
        except (ValueError,KeyError): continue
        if now-timedelta(hours=24)<=first<=now and job.get('eligibility')=='eligible': selected.append(job)
    return '# Newly discovered eligible leads — not an availability-verified shortlist\n\n'+'\n'.join('- '+j['title']+' | '+j.get('company','')+' | '+j['job_url'] for j in selected[:30])+'\n'
