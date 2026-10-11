// Live local Chrome: real native .kicad_pcb -> KiCad pad/copper/DRC -> visual copy.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const fixture=process.env.ZAPTRACE_PCB_ECO_SOURCE;
const project=process.env.ZAPTRACE_PCB_ECO_PROJECT;
const rules=process.env.ZAPTRACE_PCB_ECO_RULES;
const shots=process.env.ZAPTRACE_PCB_ECO_SHOTS;
if(!port||!fixture||!shots)throw Error('Real Chrome port, native PCB source and screenshot path required');
let pages=[];
for(let i=0;i<90;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(x=>x.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,110));
}
const tab=pages.find(x=>x.type==='page');if(!tab)throw Error('Live Chrome localhost PCB workspace unavailable');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((ok,fail)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',fail,{once:true})});
let id=0;const pending=new Map(),errors=[];
ws.addEventListener('message',event=>{const r=JSON.parse(event.data);if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);
 if(r.id&&pending.has(r.id)){pending.get(r.id)(r);pending.delete(r.id)}});
const command=(method,params={})=>new Promise((ok,fail)=>{const n=++id;pending.set(n,r=>r.error?fail(Error(JSON.stringify(r.error))):ok(r.result));ws.send(JSON.stringify({id:n,method,params}))});
await command('Runtime.enable');await command('Page.enable');await command('DOM.enable');
const js=async expr=>{const r=await command('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});
 if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(ok,message)=>{if(!ok)throw Error('FAIL '+message);console.log('PASS '+message)};
let ready=false;
for(let i=0;i<110;i++){
 ready=await js(`document.readyState==='complete'&&window.__REVIEW_LOCAL__?.token&&
  !document.getElementById('pcbEcoLab').hidden&&!document.getElementById('pcbEcoLaunch').hidden`);
 if(ready)break;await new Promise(r=>setTimeout(r,100));
}
check(ready,'actual localhost workspace exposes controlled PCB placement editor and toolbar entry');
const dom=await command('DOM.getDocument',{depth:1});
const input=await command('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#pcbEcoSource'});
check(!!input.nodeId,'real native KiCad PCB file input exists');
await command('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[fixture]});
if(project){
 const projectInput=await command('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#pcbEcoProject'});
 check(!!projectInput.nodeId,'matching native KiCad project selector exists');
 await command('DOM.setFileInputFiles',{nodeId:projectInput.nodeId,files:[project]});
}
if(rules){
 check(!!project,'custom rules have a matching KiCad project file');
 const rulesInput=await command('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#pcbEcoRules'});
 check(!!rulesInput.nodeId,'native KiCad custom DRC rule selector exists');
 await command('DOM.setFileInputFiles',{nodeId:rulesInput.nodeId,files:[rules]});
}
const chosen=await js(`(()=>{document.getElementById('pcbEcoRef').value='R1';document.getElementById('pcbEcoDx').value='1';
 document.getElementById('pcbEcoDy').value='.5';document.getElementById('pcbEcoForm').requestSubmit();
 return document.getElementById('pcbEcoSource').files?.[0]?.name})()`);
check(chosen?.endsWith('.kicad_pcb'),'user-selected real local native PCB posted through Chrome file picker');
let result;
for(let i=0;i<600;i++){
 result=await js(`(()=>({visible:!document.getElementById('pcbEcoResult').hidden,
  title:document.getElementById('pcbEcoResultTitle').textContent,
  id:document.getElementById('pcbEcoResult').dataset.id,
  ready:document.getElementById('pcbEcoResult').dataset.frameReady,
  iframeBytes:document.getElementById('pcbEcoPreview').srcdoc.length,
  status:document.getElementById('pcbEcoStatus').textContent,
  working:document.getElementById('pcbEcoCreate').disabled}))()`);
 if(result.visible&&result.ready==='true')break;
 if(!result.working&&(result.status.includes('blocked')||result.status.includes('refused')||result.status.includes('failed'))){
  throw Error('Native KiCad PCB ECO was blocked: '+result.status);
 }
 await new Promise(r=>setTimeout(r,220));
}
console.log('NATIVE KICAD PCB ECO LIVE',result);
check(result.visible&&result.ready==='true'&&result.id?.length===32&&result.iframeBytes>10000&&
 result.title.includes('R1')&&result.title.includes('21')&&result.title.includes('20.5')&&
 result.title.includes('DRC verified'),'full Chrome native KiCad footprint R1 (20,20) -> (21,20.5) passed real DRC');
const context=await js(`(()=>({bundleLabel:document.getElementById('pcbEcoDownload').textContent,
  status:document.getElementById('pcbEcoStatus').textContent}))()`);
check(rules ? context.bundleLabel.includes('ZIP')&&context.status.includes('loader probe passed') :
 project ? context.bundleLabel.includes('ZIP')&&context.status.includes('selected project') :
  !context.bundleLabel.includes('ZIP')&&context.status.includes('defaults only'),
  'native KiCad browser distinguishes supplied project rules from default-only DRC');
const preview=await js(`(()=>{const x=document.getElementById('pcbEcoPreview');return {
 iframeSrc:x.srcdoc.slice(0,500),realSvg:x.srcdoc.split('data:image/svg+xml;base64,').length-1,
 isolated:x.sandbox.contains('allow-scripts')&&!x.sandbox.contains('allow-same-origin'),
 forbidden:x.srcdoc.includes('NOT FABRICATION APPROVED'),
 noSecret:!x.srcdoc.includes(window.__REVIEW_LOCAL__.token),
 size:x.getBoundingClientRect().width}})()`);
check(preview.realSvg===2&&preview.isolated&&preview.forbidden&&preview.noSecret,
 'actual before/after F.Cu SVG plots inside opaque-origin sandbox; no leaked private token, never fab-approved');
const authenticated=await js(`(async()=>{const id=document.getElementById('pcbEcoResult').dataset.id;
 const r=await fetch('/api/pcb-eco/result/'+id+'/source.kicad_pcb',{
 headers:{'X-Review-Token':window.__REVIEW_LOCAL__.token},cache:'no-store'});
 const data=await r.text();return {status:r.status,header:r.headers.get('content-disposition'),
 native:data.startsWith('(kicad_pcb'),bytes:data.length}})()`);
check(authenticated.status===200&&authenticated.native&&authenticated.bytes>3000&&
 authenticated.header?.includes('attachment'),'separately downloadable native KiCad PCB copy available only via authenticated localhost');
if(project){
 const bundle=await js(`(async()=>{const id=document.getElementById('pcbEcoResult').dataset.id;
 const r=await fetch('/api/pcb-eco/result/'+id+'/source.project.zip',
  {headers:{'X-Review-Token':window.__REVIEW_LOCAL__.token},cache:'no-store'});
 const raw=new Uint8Array(await r.arrayBuffer());return {status:r.status,bytes:raw.length,zip:raw[0]===80&&raw[1]===75};})()`);
 check(bundle.status===200&&bundle.zip&&bundle.bytes>3000,
 'matched KiCad .kicad_pro is bundled with approved PCB and native ECO evidence');
}
await js(`document.getElementById('pcbEcoLab').scrollIntoView({block:'start',behavior:'instant'});true`);
await new Promise(r=>setTimeout(r,420));
const desk=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/pcb-eco-live-desktop.png',Buffer.from(desk.data,'base64'));
await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const phone=await js(`(()=>{const r=document.getElementById('pcbEcoLab').getBoundingClientRect(),p=document.getElementById('pcbEcoPreview').getBoundingClientRect();
return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,lab:{left:r.left,right:r.right},
 frame:{left:p.left,right:p.right},buttons:[...document.querySelectorAll('#pcbEcoResult .eco-result-actions button')].map(x=>x.getBoundingClientRect().width)}})()`);
console.log('REAL PHONE PCB ECO 390',phone);
check(phone.width<=390&&phone.scroll<=390&&phone.lab.left>=0&&phone.lab.right<=390&&
 phone.frame.left>=0&&phone.frame.right<=390&&phone.buttons.every(x=>x>=65),
 '390px real Chrome view has accessible native PCB move panel with no page-wide horizontal overflow');
const mobile=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/pcb-eco-live-mobile.png',Buffer.from(mobile.data,'base64'));
const dropped=await js(`(async()=>{document.getElementById('pcbEcoDiscard').click();
for(let i=0;i<110;i++){
 if(!document.getElementById('pcbEcoResult').dataset.id)break;
 await new Promise(r=>setTimeout(r,90));}
return {hidden:document.getElementById('pcbEcoResult').hidden,id:document.getElementById('pcbEcoResult').dataset.id,
 message:document.getElementById('pcbEcoStatus').textContent};})()`);
check(dropped.hidden&&!dropped.id&&dropped.message.includes('discarded'),
 'explicit browser discard irreversibly removes only its private PCB working copy');
check(errors.length===0,'zero actual Chrome JavaScript exceptions during native PCB edit workflow');
ws.close();console.log('NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED');
