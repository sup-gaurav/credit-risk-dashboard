import json, logging, multiprocessing as mp, re, time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from pathlib import Path

REPORT=Path('diagnostics/source_report.json')

def category(status=None, text=''):
    if status in (401,403) or re.search(r'\b401\b|\b403\b|captcha|access denied|forbidden|sign.in required',text,re.I): return 'access_required_or_refused'
    if status==429 or re.search(r'\b429\b',text): return 'rate_limited'
    if status==406: return 'request_not_acceptable'
    if status in (500,502,503,504): return 'transient_server_error'
    if re.search(r'timeout|timed out|connectionerror|connection reset',text,re.I): return 'transient_timeout_or_connection'
    return 'adapter_error' if text else 'ok'

def retry_delay(value, attempt, now=None):
    now=now or datetime.now(timezone.utc)
    if value:
        try: return max(0,int(value))
        except ValueError:
            try: return max(0,int((parsedate_to_datetime(value)-now).total_seconds())+1)
            except (TypeError,ValueError): pass
    return 20*(2**(attempt-1))

def safe_excerpt(text):
    text=re.sub(r'<[^>]+>',' ',text)
    text=re.sub(r'(?i)(token|password|authorization|cookie|secret|session|csrf)[\s"\x27:=]+[^\s,;<>]+',r'\1=[REDACTED]',text)
    return re.sub(r'\s+',' ',text)[:400]

def worker(source, output):
    result={'source':source}
    try:
        if source=='naukri_api':
            import requests
            response=requests.get('https://www.naukri.com/jobapi/v3/search',params={'noOfResults':10,'urlType':'search_by_keyword','searchType':'adv','keyword':'credit risk','pageNo':1,'k':'credit risk','seoKey':'jobs','src':'jobsearchDesk'},headers={'User-Agent':'CreditRiskDashboardDiagnostics/1.0','Accept':'application/json','Systemid':'Naukri','Appid':'109'},timeout=(10,20),allow_redirects=False)
            content_type=response.headers.get('Content-Type','')
            result.update(http_status=response.status_code,content_type=content_type,retry_after=response.headers.get('Retry-After',''),body_excerpt=safe_excerpt(response.text[:8000]))
            if 300<=response.status_code<400: result.update(status='redirect_requires_review')
            elif response.status_code!=200: result.update(status=category(response.status_code))
            else:
                try:
                    payload=response.json(); jobs=payload.get('jobDetails') if isinstance(payload,dict) else None
                    result.update(status='ok' if isinstance(jobs,list) else 'response_schema_error',result_count=len(jobs) if isinstance(jobs,list) else None)
                except ValueError: result.update(status='response_not_json')
        else:
            from jobspy import scrape_jobs
            from jobspy.model import Site
            available=[str(s.value).lower() for s in Site]
            result['available_sites']=available
            if source=='naukri_adapter' and 'naukri' not in available:
                result['status']='adapter_unavailable_in_pinned_version'
            else:
                site='linkedin' if source=='linkedin' else 'naukri'
                errors=[]
                class Capture(logging.Handler):
                    def emit(self,record):
                        if record.levelno>=logging.ERROR: errors.append(record.getMessage())
                handler=Capture();logging.getLogger().addHandler(handler)
                for name,logger in list(logging.Logger.manager.loggerDict.items()):
                    if name.lower().startswith('jobspy') and isinstance(logger,logging.Logger):logger.addHandler(handler)
                frame=scrape_jobs(site_name=[site],search_term='credit risk',location='India',country_indeed='india',results_wanted=10,hours_old=168,linkedin_fetch_description=False)
                rows=[] if frame is None else frame.to_dict('records')
                result.update(status=category(text='; '.join(errors)),result_count=len(rows),errors=[safe_excerpt(e) for e in dict.fromkeys(errors)][:3],samples=[])
                for row in rows[:5]:result['samples'].append({k:str(row.get(k,'')) for k in ['title','company','location','job_url']})
    except Exception as exc:result.update(status=category(text=type(exc).__name__+': '+str(exc)),error=safe_excerpt(str(exc)))
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    report={'started_at':datetime.now(timezone.utc).isoformat(),'python_jobspy':version('python-jobspy'),'mode':'isolated_diagnostic_not_a_deep_scan','production_data_modified':False,'sources':{}}
    def save():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save();context=mp.get_context('spawn')
    for source in ['linkedin','naukri_api','naukri_adapter']:
        attempts=[];report['sources'][source]=attempts
        for attempt in [1,2]:
            path=REPORT.parent/(source+'_attempt.json')
            if path.exists():path.unlink()
            start=time.monotonic();process=context.Process(target=worker,args=(source,str(path)));process.start()
            limit=120 if source=='linkedin' else 45 if source=='naukri_api' else 60
            process.join(limit)
            if process.is_alive():process.terminate();process.join(3)
            if process.is_alive():process.kill();process.join()
            try:result=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):result={'source':source,'status':'transient_timeout_or_connection','error':f'Worker failed or exceeded {limit}s; cause not established'}
            result.update(attempt=attempt,elapsed_seconds=round(time.monotonic()-start,1));attempts.append(result);save()
            print(f"{source}: attempt={attempt} status={result['status']} results={result.get('result_count','unknown')}",flush=True)
            recoverable=result['status'] in ['transient_timeout_or_connection','transient_server_error','rate_limited']
            if not recoverable or attempt==2 or result.get('result_count',0):break
            delay=retry_delay(result.get('retry_after',''),attempt)
            if delay>120:
                result['next_retry_not_before']=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat();result['retry_deferred']=True;save();break
            print(f'Waiting {delay}s before one retry',flush=True);time.sleep(delay)
    report['finished_at']=datetime.now(timezone.utc).isoformat();save()
    print('Diagnostic report saved. Production scanner and dashboard were not changed.',flush=True)

if __name__=='__main__':main()
