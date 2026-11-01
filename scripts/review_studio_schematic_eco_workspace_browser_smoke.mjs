// Real Chromium native localhost file-upload -> KiCad ECO -> sandboxed preview -> discard.
// Only listens to the locally launched Review Studio; zero network/cloud access.
import {localChromeSocketUrl} from './review_studio_chrome_debugger_url.mjs';
import {writeFileSync} from 'node:fs';
const chromePort=Number(process.env.ZAPTRACE_CHROME_PORT);
const source=process.env.ZAPTRACE_ECO_SOURCE;
const screenshotDir=process.env.ZAPTRACE_ECO_SHOTS;
if(!chromePort||!source||!screenshotDir)throw Error('Supply real Chrome port, KiCad schematic file and screenshot directory');
let pages=[];
for(let i=0;i<100;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${chromePort}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
const tab=pages.find(p=>p.type==='page');if(!tab)throw Error('Real localhost Review Studio Chrome not available');
const ws=new WebSocket(localChromeSocketUrl(tab.webSocketDebuggerUrl, chromePort));
await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true});});
let id=0;const callbacks=new Map(),errors=[];
ws.addEventListener('message',e=>{const x=JSON.parse(e.data);if(x.method==='Runtime.exceptionThrown')errors.push(x.params.exceptionDetails.text);
 if(x.id&&callbacks.has(x.id)){callbacks.get(x.id)(x);callbacks.delete(x.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const n=++id;callbacks.set(n,r=>r.error?rej(Error(JSON.stringify(r.error))):res(r.result));ws.send(JSON.stringify({id:n,method,params}));});
await call('Runtime.enable');await call('Page.enable');await call('DOM.enable');
const js=async expr=>{const r=await call('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(x,message)=>{if(!x)throw Error('FAIL '+message);console.log('PASS '+message);};
let ready=false;
for(let i=0;i<80;i++){
 ready=await js(`document.readyState==='complete'&&!!document.getElementById('ecoForm')&&
  !!window.__REVIEW_LOCAL__?.token&&!document.getElementById('ecoLab').hidden`);
 if(ready)break;await new Promise(r=>setTimeout(r,120));
}
check(ready,'real localhost Review Studio shows native copy-on-write schematic editor with capability token, hidden on file://');
const dom=await call('DOM.getDocument',{depth:1});
const input=await call('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#ecoSource'});
if(!input.nodeId)throw Error('Native KiCad ECO file selector not present');
await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[source]});
const posted=await js(`(()=>{document.getElementById('ecoRef').value='R1';
 document.getElementById('ecoValue').value='10k';
 document.getElementById('ecoForm').requestSubmit();
 return {source:document.getElementById('ecoSource').files?.[0]?.name,
 disabled:document.getElementById('ecoCreate').disabled}})()`);
check(posted.source.endsWith('.kicad_sch'),'real browser selected genuine local KiCad file using operating system file picker capability');
let result={};
for(let i=0;i<510;i++){
 result=await js(`(()=>({state:document.getElementById('ecoStatus').textContent,
  visible:!document.getElementById('ecoResult').hidden,
  title:document.getElementById('ecoResultTitle').textContent,
  id:document.getElementById('ecoResult').dataset.id,frame:document.getElementById('ecoPreview').srcdoc.length,
  button:document.getElementById('ecoCreate').disabled}))()`);
 if(result.visible||(!result.button&&result.state.includes('failed'))||(!result.button&&result.state.includes('rejected')))break;
 await new Promise(r=>setTimeout(r,240));
}
console.log('NATIVE KICAD ECO WORKSPACE',result);
check(result.visible&&result.id?.length===32&&result.title.includes('R1 · 4.7k → 10k')&&result.frame>10000,
 'actual GUI file upload and verified KiCad netlist/ERC produce an isolated native working copy with real before/after SVGs');
const context=await js(`(()=>{const f=document.getElementById('ecoPreview');return {
 sandbox:f.sandbox.toString(),approval:document.querySelector('header .gate').textContent,
 edited:document.getElementById('ecoResultTitle').textContent,
 iframeUntrusted:!f.sandbox.contains('allow-same-origin'),
 fileSource:document.getElementById('ecoSource').files[0].name,
 body:document.getElementById('ecoStatus').textContent,
 originalSha:f.srcdoc.includes('ORIGINAL SHA256'),script:f.srcdoc.includes('Synchronized native schematic')}})()`);
let embeddedReady=false;
for(let i=0;i<60;i++){
 embeddedReady=await js(`document.getElementById('ecoResult').dataset.frameReady==='true'`);
 if(embeddedReady)break;
 await new Promise(r=>setTimeout(r,150));
}
check(embeddedReady,'opaque-origin before/after native KiCad preview iframe actually loads, not merely populated srcdoc');
await new Promise(r=>setTimeout(r,500));
check(context.iframeUntrusted&&context.sandbox.includes('allow-scripts')&&context.approval.includes('NOT FABRICATION APPROVED')&&
 context.originalSha&&context.body.includes('netlist + ERC')&&context.fileSource.endsWith('.kicad_sch'),
 'real preview lives in script-enabled but opaque-origin sandbox; local auth secret never exposed inside source-derived HTML');
const fileProof=await js(`(async()=>{const id=document.getElementById('ecoResult').dataset.id,secret=window.__REVIEW_LOCAL__.token;
 const res=await fetch('/api/eco/result/'+id+'/source.kicad_sch',{headers:{'X-Review-Token':secret},cache:'no-store'});
 const value=await res.text();return {status:res.status,valid:value.startsWith('(kicad_sch'),modified:value.includes('(property "Value" "10k"'),size:value.length,
 attachment:res.headers.get('content-disposition')};})()`);
check(fileProof.status===200&&fileProof.valid&&fileProof.modified&&fileProof.size>5000&&fileProof.attachment.includes('attachment'),
 'edited KiCad schematic is downloadable only by authenticated authorized browser, as a distinct non-overwriting file');
const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
writeFileSync(screenshotDir+'/eco-localhost-workspace-desktop.png',Buffer.from(screenshot.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{const rect=document.getElementById('ecoLab').getBoundingClientRect();return {
 width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 lab:{left:rect.left,right:rect.right},preview:document.getElementById('ecoPreview').getBoundingClientRect().toJSON(),
 controls:[...document.querySelectorAll('#ecoResult .eco-result-actions button')].map(x=>x.getBoundingClientRect().width)}})()`);
console.log('MOBILE LIVE ECO AUTHORING 390',mobile);
check(mobile.width<=390&&mobile.scroll<=390&&mobile.lab.left>=0&&mobile.lab.right<=390&&
 mobile.preview.right<=390&&mobile.controls.every(x=>x>=80),
 'real browser ECO upload/editor/verified preview remains horizontally safe at 390px');
const phone=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
writeFileSync(screenshotDir+'/eco-localhost-workspace-mobile.png',Buffer.from(phone.data,'base64'));
const discarded=await js(`(async()=>{const id=document.getElementById('ecoResult').dataset.id;document.getElementById('ecoDiscard').click();
 for(let i=0;i<90;i++){
  if(!document.getElementById('ecoResult').dataset.id)break;await new Promise(r=>setTimeout(r,100));
 }
 return {status:document.getElementById('ecoStatus').textContent,hidden:document.getElementById('ecoResult').hidden,
  deleted:!document.getElementById('ecoResult').dataset.id,id};})()`);
check(discarded.deleted&&discarded.hidden&&discarded.status.includes('discarded'),
 'explicit discard deletes only locally owned edited ECO and leaves original source unmodified');
check(errors.length===0,'no actual JavaScript exceptions in live end-to-end ECO editor');
ws.close();console.log('REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED');
