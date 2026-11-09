(()=>{
'use strict';
const repo='sup-gaurav/credit-risk-dashboard',workflow='dashboard.yml',prefix='Credit Risk Scan ';
const box=document.createElement('section'),message=document.createElement('p'),link=document.createElement('a'),logs=document.createElement('a');
box.className='notice';link.textContent='Request a background scan on GitHub';link.target='_blank';link.rel='noopener noreferrer';logs.textContent='Open live run status';logs.href='https://github.com/'+repo+'/actions/workflows/'+workflow;logs.target='_blank';logs.rel='noopener noreferrer';
let pending=null,nextApi=0,run=null;
try{pending=JSON.parse(sessionStorage.getItem('credit-risk-scan-request')||'null')}catch(_){}
const id=crypto.randomUUID();
link.href='https://github.com/'+repo+'/issues/new?template=scan-request.yml&title='+encodeURIComponent('[SCAN] '+id)+'&request_id='+encodeURIComponent(id);
const explanation=document.createElement('p');explanation.textContent='GitHub-only: open the request, then click Submit new issue while signed in as sup-gaurav. Other users cannot dispatch scans. No GitHub token is stored in this page. Requests can be declined if another scan is active or within the five-minute cooldown; read the issue comment.';
box.append(link,document.createTextNode(' · '),logs,explanation,message);document.querySelector('header').after(box);
link.onclick=()=>{pending={id,created:Date.now()};run=null;nextApi=0;try{sessionStorage.setItem('credit-risk-scan-request',JSON.stringify(pending))}catch(_){}message.textContent='Finish submitting the issue in GitHub. Awaiting a matching workflow; a scan has not yet been confirmed.';};
function finish(text){message.textContent=text;pending=null;run=null;try{sessionStorage.removeItem('credit-risk-scan-request')}catch(_){}}
async function poll(){
if(!pending||document.hidden)return;
if(Date.now()-pending.created>5400000){finish('Automatic monitoring stopped after 90 minutes. Check GitHub Actions and the request issue. This does not cancel the scan.');return;}
try{
 if(Date.now()>=nextApi){
  nextApi=Date.now()+120000;
  const endpoint=run?'https://api.github.com/repos/'+repo+'/actions/runs/'+run.id:'https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow+'/runs?event=workflow_dispatch&branch=main&per_page=30';
  const response=await fetch(endpoint,{cache:'no-store',headers:{Accept:'application/vnd.github+json'}});
  if(!response.ok)throw Error('GitHub status HTTP '+response.status);
  const result=await response.json();run=run?result:(result.workflow_runs||[]).find(r=>r.display_title===prefix+pending.id)||null;
 }
 if(!run){message.textContent='Awaiting GitHub submission or a matching run. If no run appears, check the request issue for a declined request or dispatch error.';return;}
 logs.href='https://github.com/'+repo+'/actions/runs/'+run.id;
 if(run.status!=='completed'){message.textContent='Matching GitHub run #'+run.run_number+': '+run.status+'. Published results may still be from the previous scan.';return;}
 if(run.conclusion!=='success'){finish('Matching run ended: '+run.conclusion+'. Open live run status for details.');return;}
 const response=await fetch('jobs.json?t='+Date.now(),{cache:'no-store'});if(!response.ok)throw Error('Snapshot HTTP '+response.status);
 const snapshot=await response.json();
 if(String(snapshot.run_id)!==String(run.id)){
  if(Date.parse(snapshot.last_scan)>Date.parse(run.updated_at)){if(typeof window.load==='function')await window.load();finish('Requested run finished; a newer published snapshot is now available. Check source health for incomplete coverage.');return;}
  message.textContent='Requested run succeeded; waiting for its published snapshot to become available.';return;
 }
 if(typeof window.load==='function')await window.load();
 finish('Requested run finished and its snapshot is available: '+(snapshot.jobs||[]).length+' saved freshness-qualified candidates. This does not establish exhaustive coverage or verified availability.');
}catch(error){message.textContent='Status check unavailable: '+error.message+'. Use Open live run status; no scan success is being assumed.';}
}
if(pending)message.textContent='Resuming monitoring of your GitHub scan request.';
setInterval(poll,15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});poll();
})();
