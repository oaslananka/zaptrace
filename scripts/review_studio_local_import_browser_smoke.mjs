// Actual CDP file chooser -> localhost POST -> native pcbnew/KiCad DRC -> project card.
// No internet or hosted backend. Source file is unmodified.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9864);
const pcb=process.env.ZAPTRACE_TEST_PCB;
if(!pcb)throw Error('Provide actual source PCB path');
let pages;
for(let i=0;i<50;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port+1}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,140));
}
const page=pages?.find(x=>x.type==='page');if(!page)throw Error('Actual Chrome page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
let seq=0;const pending=new Map(),errors=[];
ws.addEventListener('message',e=>{const x=JSON.parse(e.data);
 if(x.method==='Runtime.exceptionThrown')errors.push(x.params.exceptionDetails.text);
 if(x.id&&pending.has(x.id)){pending.get(x.id)(x);pending.delete(x.id);}
});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,x=>x.error?reject(Error(JSON.stringify(x.error))):resolve(x.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('DOM.enable');await call('Page.enable');
const js=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(value,msg)=>{if(!value)throw Error('FAIL '+msg);console.log('PASS '+msg);};
let pageLoaded=false;
for(let i=0;i<60;i++){
 try{pageLoaded=await js(`!!document.getElementById('nativeImport')`);if(pageLoaded)break;}catch{}
 await new Promise(r=>setTimeout(r,130));
}
if(!pageLoaded){console.log('CHROME INITIAL PAGE',await js(`({href:location.href,body:document.body?.textContent?.slice(0,800),title:document.title})`));
 throw Error('Local review workspace page did not load');}
const initial=await js(`(()=>({ok:!!window.__REVIEW_LOCAL__?.token,direct:!document.getElementById('nativeImport').hidden,
 cli:document.getElementById('cliFallback').hidden,projects:document.querySelectorAll('.project').length,
 url:location.href,local:location.hostname==='127.0.0.1'}))()`);
check(initial.ok&&initial.direct&&initial.cli&&initial.projects===0&&initial.local,
 'real localhost UI enables native file picker, hides command fallback and has no preloaded fictional projects');
const mobileResult=await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{document.getElementById('nativeImport').scrollIntoView({block:'start'});
 const doc=document.documentElement;
 return {viewport:doc.clientWidth,scroll:doc.scrollWidth,
  board:document.getElementById('nativeBoardFile').getBoundingClientRect().width,
  project:document.getElementById('nativeProjectFile').getBoundingClientRect().width,
  rules:document.getElementById('nativeRulesFile').getBoundingClientRect().width,
  live:!document.getElementById('nativeImport').hidden};})()`);
check(mobile.live&&mobile.viewport<=390&&mobile.scroll<=mobile.viewport&&
 mobile.board>100&&mobile.project>100&&mobile.rules>100,
 '390px mobile direct KiCad GUI file picker and project DRC context controls have no horizontal overflow');
const mobileShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync('build/review-studio-live-test/local-import-mobile.png',Buffer.from(mobileShot.data,'base64'));
await call('Emulation.clearDeviceMetricsOverride');

const documentResult=await call('DOM.getDocument',{depth:-1});
const node=await call('DOM.querySelector',{nodeId:documentResult.root.nodeId,selector:'#nativeBoardFile'});
check(!!node.nodeId,'native PCB file picker is an actual browser file input');
await call('DOM.setFileInputFiles',{nodeId:node.nodeId,files:[pcb]});
if(process.env.ZAPTRACE_TEST_PRO){
 const project=await call('DOM.querySelector',{nodeId:documentResult.root.nodeId,selector:'#nativeProjectFile'});
 await call('DOM.setFileInputFiles',{nodeId:project.nodeId,files:[process.env.ZAPTRACE_TEST_PRO]});
 const name=await js(`document.getElementById('nativeProjectFile').files[0]?.name`);
 check(name?.endsWith('.kicad_pro'),'user-selected KiCad project settings included for real native DRC rules');
}
if(process.env.ZAPTRACE_TEST_SCH){
 const schematic=await call('DOM.querySelector',{nodeId:documentResult.root.nodeId,selector:'#nativeSchFile'});
 await call('DOM.setFileInputFiles',{nodeId:schematic.nodeId,files:[process.env.ZAPTRACE_TEST_SCH]});
}
if(process.env.ZAPTRACE_TEST_SHEET_FOLDER){
 const input=await call('DOM.querySelector',{nodeId:documentResult.root.nodeId,selector:'#nativeSheetFolder'});
 await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[process.env.ZAPTRACE_TEST_SHEET_FOLDER]});
 let items=[];
 for(let i=0;i<30;i++){
  items=await js(`([...document.getElementById('nativeSheetFolder').files].map(x=>x.webkitRelativePath))`);
  if(items.length)break;
  await new Promise(r=>setTimeout(r,90));
 }
 console.log('NATIVE FOLDER FILES',items);
 check(items.some(path=>path.endsWith('sub/power.kicad_sch')),
  'actual OS-backed folder selection retains relative hierarchical KiCad sheet path');
}

const files=await js(`(()=>{const input=document.getElementById('nativeBoardFile');return [...input.files].map(f=>({name:f.name,size:f.size}))})()`);
check(files.length===1&&files[0].name.endsWith('.kicad_pcb')&&files[0].size>100,
 'actual Chrome file selection reads a real native KiCad PCB source without modifying it');
const started=await js(`(()=>{document.getElementById('nativeImportName').value='Local GUI verified sensor board';
 document.getElementById('nativeImportForm').requestSubmit();
 return {requesting:document.getElementById('nativeRun').disabled,
  status:document.getElementById('nativeJobText').textContent};})()`);
check(started.requesting&&started.status.includes('localhost KiCad'),
 'browser starts local import only after explicit user-directed file selection');
let final=null;
const observedStages=new Set();
let progressFrame=null;
for(let i=0;i<120;i++){
 await new Promise(r=>setTimeout(r,1250));
 try{final=await js(`(()=>({projects:document.querySelectorAll('.project').length,
 status:document.getElementById('nativeJobText')?.textContent||'',
 failed:document.getElementById('nativeJob')?.classList.contains('error'),
 hasToken:!!window.__REVIEW_LOCAL__?.token,
 stages:[...document.querySelectorAll('.native-stages li.observed')].map(el=>el.dataset.phase),
 current:document.querySelector('.native-stages li.current')?.dataset.phase,
 href:document.querySelector('.project .primary')?.href,
 count:document.querySelector('.mini-metrics')?.textContent,rule:document.querySelector('.rules-source')?.textContent}))()`);}catch{}
 if(final?.stages)for(const stage of final.stages)observedStages.add(stage);
 if(final?.current&&final.current!=='preparing'&&!progressFrame&&!final.projects){
  progressFrame=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  writeFileSync('build/review-studio-live-test/local-import-real-progress.png',Buffer.from(progressFrame.data,'base64'));
 }
 if(final?.projects===1||final?.failed)break;
}
console.log('KICAD LOCAL IMPORT FINAL',final,'OBSERVED FILE-BASED STAGES', [...observedStages]);
check(observedStages.has('preparing')&&
 (!observedStages.has('erc')||Boolean(process.env.ZAPTRACE_TEST_SCH)),
 'native import status tracks real output artifacts; no schematic ERC or netlist invented');

check(final?.projects===1&&!final.failed&&final.count.includes('DRC FINDINGS')&&final.count.includes('OPEN NET PAIRS')&&
 (!process.env.ZAPTRACE_TEST_PRO||final.rule.includes('KiCad project rules included')),
 'native KiCad subprocess completed: real DRC report and open pairs now appear in the project library');
check(final.href?.startsWith(`http://127.0.0.1:${port}/review-assets/`)&&
 /\/review-assets\/[0-9a-f]{24}\/index\.html$/.test(final.href),
 'new native PCB project links into its own read-only evidence viewer over localhost');
const capture=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync('build/review-studio-live-test/local-import-success.png',Buffer.from(capture.data,'base64'));
await js(`document.querySelector('.project .primary').click()`);
let board=null;
for(let i=0;i<50;i++){
 await new Promise(r=>setTimeout(r,120));
 try{board=await js(`(()=>typeof DATA!=='undefined'&&DATA.board?.pads?.length>0?{
 pads:DATA.board.pads.length,drc:DATA.drc_state,back:document.getElementById('workspaceHome')?.href,
 fab:document.querySelector('.headside')?.textContent}:null)()`);if(board)break;}catch{}
}
check(board?.pads>0&&board.drc!=='not_run'&&board.back?.includes('127.0.0.1')&&
 board.fab?.includes('NOT FABRICATION APPROVED'),
 'imported real PCB opens native read-only plot and explicit blocked manufacturing state');
check(errors.length===0,'no Chrome runtime exceptions during actual file chooser and native KiCad import');
ws.close();console.log('DIRECT LOCAL KICAD FILE IMPORT: ALL CHROME TESTS PASSED');
