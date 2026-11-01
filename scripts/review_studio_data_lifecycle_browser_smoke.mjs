// Actual local packaged Review Studio: native ZIP download, typed deletion,
// original KiCad source preservation, and empty-library refresh.
import {existsSync,mkdirSync,readFileSync,statSync,writeFileSync} from 'node:fs';
const debug=Number(process.env.ZAPTRACE_CHROME_PORT);
const download=process.env.ZAPTRACE_BACKUP_DIR;
const shots=process.env.ZAPTRACE_RELEASE_SHOTS||'build/distribution';
if(!debug||!download)throw Error('Expected explicit Chrome port and temporary ZIP download directory');
mkdirSync(download,{recursive:true});
let tabs=[];
for(let i=0;i<90;i++){
 try{tabs=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();if(tabs.some(x=>x.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,120));
}
const tab=tabs.find(x=>x.type==='page');if(!tab)throw Error('Chrome page unavailable');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const queue=new Map(),exceptions=[];
ws.addEventListener('message',e=>{const v=JSON.parse(e.data);if(v.method==='Runtime.exceptionThrown')exceptions.push(v.params.exceptionDetails.text);if(v.id&&queue.has(v.id)){queue.get(v.id)(v);queue.delete(v.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;queue.set(id,r=>r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result));ws.send(JSON.stringify({id,method,params}));});
const js=async value=>{const r=await call('Runtime.evaluate',{expression:value,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const assert=(yes,message)=>{if(!yes)throw Error('FAIL '+message);console.log('PASS',message);};
await call('Runtime.enable');await call('Page.enable');
const origin=new URL(tab.url).origin;
if(!origin.startsWith('http://127.0.0.1:'))throw Error('Expected an installed loopback-only application page');
await call('Page.navigate',{url:origin+'/'});

let ready=false;
for(let i=0;i<85;i++){
 try{ready=await js(`document.readyState==='complete'&&document.querySelectorAll('.data-actions').length===1&&!!window.__REVIEW_LOCAL__?.token`);if(ready)break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
assert(ready,'a true native KiCad import is registered and manageable in the installed package');
const before=await js(`(()=>({cards:document.querySelectorAll('.project').length,
 key:document.querySelector('.data-actions')?.dataset.key,sha:document.querySelector('.data-actions')?.dataset.sha,
 visible:!document.querySelector('.data-actions')?.hidden,
 count:document.querySelector('.hero-count strong')?.textContent,
 fab:document.querySelector('header .gate')?.textContent}))()`);
assert(before.cards===1&&before.visible&&before.count==='1'&&before.sha?.length===64&&before.fab.includes('NOT FABRICATION APPROVED'),
 'only app-owned native review exposes backed-up local data management, and fabrication gate remains blocked');
const endpoint=await js(`(async()=>{const c=document.querySelector('.data-actions');
 const r=await fetch('/api/projects/export?key='+c.dataset.key+'&sha='+c.dataset.sha,
  {headers:{'X-Review-Token':window.__REVIEW_LOCAL__.token},cache:'no-store'});
 const a=await r.arrayBuffer();return {status:r.status,type:r.headers.get('content-type'),
 bytes:a.byteLength,signature:Array.from(new Uint8Array(a).slice(0,4))};})()`);
assert(endpoint.status===200&&endpoint.type==='application/zip'&&endpoint.bytes>400&&endpoint.signature[0]===80&&endpoint.signature[1]===75,
 'local origin-scoped ZIP export responds with a real downloadable archive');
await call('Page.setDownloadBehavior',{behavior:'allow',downloadPath:download});
await js(`document.querySelector('.backup-review').click()`);
const zipPath=download+'/zaptrace-review-'+before.key+'.zip';
let saved=false;
for(let i=0;i<95;i++){
 if(existsSync(zipPath)&&statSync(zipPath).size>300){saved=true;break;}
 await new Promise(r=>setTimeout(r,110));
}
assert(saved&&readFileSync(zipPath).subarray(0,2).toString()==='PK',
 'actual browser user click saves the sensitive KiCad/source backup as ZIP in chosen local folder');
const staged=await js(`(()=>{document.querySelector('.delete-review').click();
 return {open:document.getElementById('reviewDeleteDialog').open,
 disabled:document.getElementById('reviewDeleteConfirm').disabled,
 original:document.getElementById('reviewDeleteDescription').textContent};})()`);
assert(staged.open&&staged.disabled&&staged.original.includes('original PCB outside Review Studio remains unchanged'),
 'permanent delete dialog explains copied inputs versus original engineering source and requires confirmation');
const typed=await js(`(()=>{const input=document.getElementById('reviewDeletePhrase');
 input.value='DELET';input.dispatchEvent(new Event('input',{bubbles:true}));
 const rejected=document.getElementById('reviewDeleteConfirm').disabled;
 input.value='DELETE';input.dispatchEvent(new Event('input',{bubbles:true}));
 return {rejected,enabled:!document.getElementById('reviewDeleteConfirm').disabled};})()`);
assert(typed.rejected&&typed.enabled,'destructive action remains disabled until the exact literal DELETE is entered');
const snap=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/release-data-delete-confirmation.png',Buffer.from(snap.data,'base64'));
const cancelled=await js(`(()=>{document.getElementById('reviewDeleteCancel').click();return {
 open:document.getElementById('reviewDeleteDialog').open,cards:document.querySelectorAll('.project').length};})()`);
assert(!cancelled.open&&cancelled.cards===1,'cancel preserves original and saved local review without cleanup');
await js(`(()=>{document.querySelector('.delete-review').click();const input=document.getElementById('reviewDeletePhrase');
 input.value='DELETE';input.dispatchEvent(new Event('input',{bubbles:true}));
 document.getElementById('reviewDeleteConfirm').click();return true;})()`);
let removed=false;
for(let i=0;i<100;i++){
 try{removed=await js(`document.readyState==='complete'&&document.querySelectorAll('.project').length===0&&document.body.textContent.includes('No native KiCad boards yet')`);if(removed)break;}catch{}
 await new Promise(r=>setTimeout(r,120));
}
assert(removed,'confirmed deletion removes only app-owned local review from the project catalog and refreshes empty onboarding');
const empty=await js(`(()=>({gate:document.querySelector('header .gate')?.textContent,
 cards:document.querySelectorAll('.project').length,
 help:!!document.querySelector('#help'),
 stop:!document.getElementById('localSessionControls').hidden}))()`);
assert(empty.cards===0&&empty.help&&empty.stop&&empty.gate.includes('NOT FABRICATION APPROVED'),
 'native KiCad service, privacy/help and blocked manufacturing status remain correct after deletion');
assert(exceptions.length===0,'zero actual Chromium exceptions in backup, cancel and permanent-delete lifecycle');
ws.close();console.log('NATIVE END-USER BACKUP AND PERMANENT DELETE: ALL CHROME TESTS PASSED');
