// Installed end-user ZIP restoration: select real backup in Chromium, import
// *native KiCad sources only*, and independently regenerate ERC + DRC.
import {localChromeSocketUrl} from './review_studio_chrome_debugger_url.mjs';
import {existsSync,writeFileSync} from 'node:fs';
const debug=Number(process.env.ZAPTRACE_CHROME_PORT);
const zip=process.env.ZAPTRACE_RESTORE_ZIP;
const screenshots=process.env.ZAPTRACE_RELEASE_SHOTS||'build/distribution';
if(!debug||!zip||!existsSync(zip))throw Error('Real Chrome port and exported native KiCad ZIP required');
let pages=[];
for(let i=0;i<100;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();if(pages.some(x=>x.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,110));
}
const page=pages.find(x=>x.type==='page');if(!page)throw Error('Chrome debug browser not available');
const ws=new WebSocket(localChromeSocketUrl(page.webSocketDebuggerUrl, debug));
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let next=0;const pending=new Map(),errors=[];
ws.addEventListener('message',e=>{const v=JSON.parse(e.data);
 if(v.method==='Runtime.exceptionThrown')errors.push(v.params.exceptionDetails.text);
 if(v.id&&pending.has(v.id)){pending.get(v.id)(v);pending.delete(v.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;
 pending.set(id,v=>v.error?reject(Error(JSON.stringify(v.error))):resolve(v.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('DOM.enable');await call('Page.enable');
const js=async code=>{const r=await call('Runtime.evaluate',{expression:code,returnByValue:true,awaitPromise:true});
 if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,msg)=>{if(!v)throw Error('FAIL '+msg);console.log('PASS '+msg);};
const origin=new URL(page.url).origin;
check(origin.startsWith('http://127.0.0.1:'),'restoration operates on the localhost-only installed Review Studio');
await call('Page.navigate',{url:origin+'/'});
let ready=false;
for(let i=0;i<70;i++){
 try{ready=await js(`document.readyState==='complete'&&
 !!document.getElementById('nativeRestoreForm')&&
 !document.getElementById('nativeRestore').hidden&&
 document.querySelectorAll('.project').length===0`);if(ready)break;}catch{}
 await new Promise(r=>setTimeout(r,140));
}
check(ready,'backup restore form appears on a fresh, empty, installed project workspace');
const dom=await call('DOM.getDocument',{depth:1});
const file=await call('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#nativeRestoreZip'});
if(!file.nodeId)throw Error('Native ZIP file selector absent');
await call('DOM.setFileInputFiles',{nodeId:file.nodeId,files:[zip]});
const submit=await js(`(()=>{
 document.getElementById('nativeRestoreName').value='Recovered actual KiCad sensor node';
 const selected=document.getElementById('nativeRestoreZip').files;
 document.getElementById('nativeRestoreForm').requestSubmit();
 return {files:selected.length,filename:selected[0]?.name,disabled:document.getElementById('nativeRestoreRun').disabled,
 data:document.getElementById('nativeRestoreStatus').textContent};})()`);
check(submit.files===1&&submit.filename.endsWith('.zip')&&submit.disabled&&submit.data.includes('Validating'),
 'actual user-facing browser input supplies a ZIP, and explicit submit starts source-SHA validation');
let received=false,failed='';
for(let i=0;i<290;i++){
 await new Promise(r=>setTimeout(r,400));
 try{
  const state=await js(`(()=>({ready:document.readyState==='complete',cards:document.querySelectorAll('.project').length,
   text:document.getElementById('nativeRestoreStatus')?.textContent,
   name:document.querySelector('.project h3')?.textContent,
   description:document.body?.textContent?.includes('NOT FABRICATION APPROVED')}))()`);
  if(state.cards===1&&state.name?.includes('Recovered actual KiCad sensor node')&&state.ready){received=true;break;}
  if(state.text?.includes(' · Existing reviews and your ZIP backup remain unchanged.')){failed=state.text;break;}
 }catch{}
}
check(received,'real restored ZIP generated an independently checked native KiCad review card; '+failed);
const detail=await js(`(()=>({cards:document.querySelectorAll('.project').length,
 name:document.querySelector('.project h3')?.textContent,
 actions:!!document.querySelector('.data-actions .backup-review'),
 source:document.querySelector('.project .ref')?.textContent,
 fab:document.querySelector('header .gate')?.textContent,
 erc:document.querySelector('.project .mini-metrics')?.textContent,
 restore:!document.getElementById('nativeRestore').hidden}))()`);
console.log('RESTORED REAL KICAD REVIEW',detail);
check(detail.cards===1&&detail.actions&&detail.restore&&detail.fab.includes('NOT FABRICATION APPROVED'),
 'restored project retains private ZIP management, native evidence and NOT FAB APPROVED gate');
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>({viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 restore:document.getElementById('nativeRestore').getBoundingClientRect().width,
 input:document.getElementById('nativeRestoreZip').getBoundingClientRect().width}))()`);
check(mobile.viewport<=390&&mobile.scroll<=390&&mobile.input>=100&&mobile.restore<391,
 'ZIP restoration remains usable at 390px mobile with no horizontal overflow');
const screen=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshots+'/release-restored-kicad-mobile.png',Buffer.from(screen.data,'base64'));
check(errors.length===0,'no browser exceptions during actual native KiCad ZIP restoration');
ws.close();console.log('NATIVE ZIP RESTORE WITH FRESH ERC/DRC: ALL CHROME TESTS PASSED');
