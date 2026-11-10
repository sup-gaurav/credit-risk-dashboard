import ipaddress, json, re, socket, time
from urllib.parse import urlparse, urljoin, quote, parse_qs
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

UA='CreditRiskDashboard/2.0 (public job research)'
VENDORS=('myworkdayjobs.com','lever.co','greenhouse.io','ashbyhq.com','oraclecloud.com')
RISK=re.compile(r'credit|risk|portfolio|model|underwrit|collections|scorecard|ifrs|basel|analytics|senior manager|director|vice president|\bavp\b|\bsvp\b|head of',re.I)

class Paused(Exception):pass

class Client:
    def __init__(self,roots,deadline):
        self.hosts={urlparse(u).hostname for u in roots if u};self.deadline=deadline;self.last={};self.robots={};self.session=requests.Session();self.session.headers['User-Agent']=UA
    def allowed(self,url):
        p=urlparse(url);host=p.hostname or ''
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):raise ValueError('Unsafe URL')
        if host not in self.hosts and not any(host==v or host.endswith('.'+v) for v in VENDORS):raise ValueError('Host not approved')
        for answer in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(answer[4][0]).is_global:raise ValueError('Non-public address')
        return host
    def guard(self):
        if time.monotonic()>=self.deadline:raise Paused('Runtime budget reached; resume saved state')
    def request(self,url,payload=None,redirects=0):
        if redirects>3:raise ValueError('Redirect limit reached')
        self.guard();host=self.allowed(url);base='https://'+host
        if host not in self.robots:
            r=self.session.get(base+'/robots.txt',timeout=15,allow_redirects=False)
            if r.status_code in (401,403):raise PermissionError('robots access refused')
            if r.status_code==200:
                parser=RobotFileParser();parser.parse(r.text.splitlines());self.robots[host]=parser
            elif r.status_code==404:self.robots[host]=None
            else:raise PermissionError('robots policy unavailable')
        parser=self.robots[host]
        if parser and not parser.can_fetch(UA,url):raise PermissionError('robots disallows this path')
        wait=1.5-(time.monotonic()-self.last.get(host,0))
        if wait>0:time.sleep(wait)
        self.guard();self.last[host]=time.monotonic()
        for _ in range(4):
            r=self.session.request('POST' if payload is not None else 'GET',url,json=payload,timeout=25,allow_redirects=False)
            if 300<=r.status_code<400:
                if payload is not None:raise ValueError('Unexpected POST redirect')
                url=urljoin(url,r.headers.get('Location',''));self.allowed(url);return self.request(url,redirects=redirects+1)
            r.raise_for_status();return r
        raise ValueError('Redirect limit reached')

def plain(value):return BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True)

def structured(document,base,company):
    soup=BeautifulSoup(document,'html.parser');jobs=[]
    def visit(obj):
        if isinstance(obj,list):
            for v in obj:visit(v)
        elif isinstance(obj,dict):
            types=obj.get('@type',[]);types=[types] if isinstance(types,str) else types
            if 'JobPosting' in types:
                locations=obj.get('jobLocation',[]);locations=[locations] if isinstance(locations,dict) else locations
                addresses=[x.get('address',{}) for x in locations if isinstance(x,dict)]
                location='; '.join(', '.join(str(a.get(k,'')) for k in ['addressLocality','addressRegion','addressCountry']) for a in addresses if isinstance(a,dict))
                hiring=obj.get('hiringOrganization') or {};identifier=obj.get('identifier') or {}
                jobs.append({'title':plain(obj.get('title','')),'company':hiring.get('name',company) if isinstance(hiring,dict) else company,'location':location,'job_url':urljoin(base,str(obj.get('url') or base)),'description':plain(obj.get('description','')),'date_posted':obj.get('datePosted',''),'requisition_id':identifier.get('value','') if isinstance(identifier,dict) else str(identifier),'valid_through':obj.get('validThrough',''),'availability':'structured_listing_present'})
            for key in ['@graph','itemListElement','item']:visit(obj.get(key))
    for tag in soup.select('script[type="application/ld+json"]'):
        try:visit(json.loads(tag.string or tag.get_text()))
        except (ValueError,TypeError):pass
    return jobs,soup

class Sink:
    def __init__(self,emit):self.emit=emit;self.count=0
    def append(self,row):self.emit(row);self.count+=1
    def __iter__(self):return iter(())
    def __len__(self):return self.count

def vendor(url,company,client,emit):
    p=urlparse(url);host=p.hostname or '';parts=p.path.strip('/').split('/');rows=Sink(emit)
    if host in ('jobs.lever.co','jobs.eu.lever.co') and parts[0]:
        root=('https://api.eu.lever.co' if host=='jobs.eu.lever.co' else 'https://api.lever.co')+'/v0/postings/'+quote(parts[0],safe='')
        for offset in range(0,10000,100):
            page=client.request(root+f'?mode=json&skip={offset}&limit=100').json()
            if not isinstance(page,list):raise ValueError('Invalid Lever schema')
            if not page:return rows,'exhausted_published_feed'
            for j in page:
                rows.append({'title':j.get('text',''),'company':company,'location':(j.get('categories') or {}).get('location','')+(', India' if j.get('country')=='IN' else ''),'job_url':j.get('hostedUrl',''),'description':j.get('descriptionPlain') or plain(j.get('description')),'date_posted':'','requisition_id':j.get('id','')})
        return rows,'safety_limit_reached'
    if host in ('boards.greenhouse.io','job-boards.greenhouse.io'):
        token=parse_qs(p.query).get('for',[parts[0]])[0]
        root='https://boards-api.greenhouse.io/v1/boards/'+quote(token,safe='')+'/jobs'
        payload=client.request(root+'?content=true').json()
        if not isinstance(payload.get('jobs'),list):raise ValueError('Invalid Greenhouse schema')
        for j in payload['jobs']:
            desc=plain(j.get('content',''));date=''
            if RISK.search(j.get('title','')+' '+desc):date=client.request(root+'/'+str(j['id'])).json().get('first_published','')
            rows.append({'title':j.get('title',''),'company':company,'location':(j.get('location') or {}).get('name',''),'job_url':j.get('absolute_url',''),'description':desc,'date_posted':date,'requisition_id':j.get('requisition_id','')})
        return rows,'exhausted_published_feed'
    if host=='jobs.ashbyhq.com' and parts[0]:
        payload=client.request('https://api.ashbyhq.com/posting-api/job-board/'+quote(parts[0],safe='')).json()
        if not isinstance(payload.get('jobs'),list):raise ValueError('Invalid Ashby schema')
        for j in payload['jobs']:
            if j.get('isListed') is False:continue
            address=(j.get('address') or {}).get('postalAddress',{})
            rows.append({'title':j.get('title',''),'company':company,'location':j.get('location','')+(', India' if address.get('addressCountry') in ('IN','IND','India') else ''),'job_url':j.get('jobUrl',''),'description':j.get('descriptionPlain') or plain(j.get('descriptionHtml')),'date_posted':j.get('publishedAt','')})
        return rows,'exhausted_published_feed'
    if host.endswith('.myworkdayjobs.com'):
        index=1 if re.fullmatch(r'[a-z]{2}-[A-Z]{2}',parts[0]) else 0
        if len(parts)==index+1:
            site=parts[index];tenant=host.split('.')[0];root='https://'+host+'/wday/cxs/'+tenant+'/'+site
            for offset in range(0,10000,20):
                payload=client.request(root+'/jobs',{'appliedFacets':{},'limit':20,'offset':offset,'searchText':''}).json()
                page=payload.get('jobPostings');total=payload.get('total')
                if not isinstance(page,list) or not isinstance(total,int):raise ValueError('Unvalidated Workday response')
                if not page:return rows,'exhausted_published_feed' if offset>=total else 'incomplete_workday_response'
                for j in page:
                    path=j.get('externalPath','');public='https://'+host+'/'+site+path
                    row={'title':j.get('title',''),'company':company,'location':j.get('locationsText',''),'job_url':public,'description':'','date_posted':''}
                    if RISK.search(row['title']) and path:
                        info=client.request(root+path).json().get('jobPostingInfo',{})
                        row['description']=plain(info.get('jobDescription',''))
                        row['job_url']=info.get('externalUrl') or public
                        row['requisition_id']=info.get('jobReqId','')
                        try:
                            extra,_=structured(client.request(row['job_url']).text,row['job_url'],company)
                            if extra:row.update(extra[0])
                        except Paused:raise
                        except Exception:pass
                    rows.append(row)
                if offset+len(page)>=total:return rows,'exhausted_published_feed'
            return rows,'safety_limit_reached'
    return None,None

def employer(entry,client,consume):
    pending=[u for u in [entry['careers_url'],entry.get('listing_url','')] if u];seen=set();issues=[];count=0;feed=False;explicit_end=False
    while pending:
        client.guard();url=pending.pop(0)
        if url in seen:continue
        if len(seen)>=2000:issues.append('safety_limit_reached');break
        seen.add(url)
        try:
            rows,status=vendor(url,entry['name'],client,lambda row:consume(row,'employer:'+entry['name']))
            if rows is not None:
                for row in rows:consume(row,'employer:'+entry['name'])
                count+=len(rows);feed=True
                if status!='exhausted_published_feed':issues.append(status)
                continue
            response=client.request(url);rows,soup=structured(response.text,url,entry['name'])
            for row in rows:consume(row,'employer:'+entry['name'])
            count+=len(rows)
            page_text=soup.get_text(' ',strip=True);numbers=re.search(r'Page\s+(\d+)\s+of\s+(\d+)',page_text,re.I)
            if numbers and numbers.group(1)==numbers.group(2):explicit_end=True
            next_links=soup.select('a[rel="next"],a.paginationItemNext,a.pagination__next,a[aria-label="Next"],a[aria-label="Next page"]')
            for a in next_links:
                if a.get('href'):pending.append(urljoin(url,a['href']))
            for a in soup.select('a[href],iframe[src]'):
                link=urljoin(url,a.get('href') or a.get('src'));lp=urlparse(link);lh=lp.hostname or ''
                recognized=lh in ('jobs.lever.co','jobs.eu.lever.co','boards.greenhouse.io','job-boards.greenhouse.io','jobs.ashbyhq.com') or lh.endswith('.myworkdayjobs.com')
                label=a.get_text(' ',strip=True)
                detail=lh==urlparse(url).hostname and re.search(r'/(?:job|job-detail)/|/jobs/\d+',lp.path,re.I) and RISK.search(label)
                if recognized or detail:
                    client.allowed(link)
                    if link not in seen and link not in pending:pending.append(link)
            if not rows and not next_links and len(seen)==1 and not pending:issues.append('requires_source_specific_adapter')
        except Paused:raise
        except Exception as exc:issues.append(type(exc).__name__+(':'+str(exc.response.status_code) if getattr(exc,'response',None) is not None else ''))
    if not feed and not explicit_end:issues.append('pagination_not_verified')
    return {'state':'completed_with_gaps' if issues else 'exhausted_accessible_listing','urls_inspected':len(seen),'returned_observations':count,'issues':sorted(set(issues)),'note':'HTML discovery uses structured JobPosting data and observed links; unhandled dynamic portals are coverage gaps, not zero vacancies'}
