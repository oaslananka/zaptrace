// Real Chrome 155 source-only localhost native KiCad guarded copper UX acceptance.
import {createHash} from 'node:crypto';
import {mkdir,readFile,readdir} from 'node:fs/promises';
import path from 'node:path';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const zip=process.env.ZAPTRACE_COPPER_ZIP;
const dir=process.env.ZAPTRACE_COPPER_DOWNLOAD_DIR;
const viaMode=process.env.ZAPTRACE_COPPER_VIA_PAIR==='1';
const customMode=process.env.ZAPTRACE_COPPER_CUSTOM_RULES==='1';
const batchMode=process.env.ZAPTRACE_COPPER_BATCH==='1';
if(!port||!zip||!dir)throw Error('Real localhost Chrome and portable KiCad ZIP required');
const initialSha=createHash('sha256').update(await readFile(zip)).digest('hex');
let pages=[];
for(let i=0;i<85;i++){
 try{pages=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();if(pages.some(x=>x.type==='page'))break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,100));
}
const tab=pages.find(x=>x.type==='page'&&x.url?.startsWith('http://127.0.0.1:'))||pages.find(x=>x.type==='page');
if(!tab)throw Error('Actual Chrome localhost Review Studio page unavailable');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{
 ws.addEventListener('open',resolve,{once:true});
 ws.addEventListener('error',reject,{once:true});
});
let id=0;const pending=new Map(),jsErrors=[];
ws.addEventListener('message',ev=>{
 const msg=JSON.parse(ev.data);
 if(msg.method==='Runtime.exceptionThrown')jsErrors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
 if(msg.id&&pending.has(msg.id)){pending.get(msg.id)(msg);pending.delete(msg.id);}
});
const cmd=(method,params={})=>new Promise((resolve,reject)=>{
 const next=++id;
 pending.set(next,r=>r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result));
 ws.send(JSON.stringify({id:next,method,params}));
});
await cmd('Runtime.enable');await cmd('Page.enable');await cmd('DOM.enable');
const evaluate=async expression=>{
 const result=await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
 if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
 return result.result.value;
};
const pass=(condition,label)=>{if(!condition)throw Error('FAIL: '+label);console.log('PASS',label);};
let ready=false;
for(let i=0;i<50;i++){
 ready=await evaluate("document.readyState==='complete'&&Boolean(window.__REVIEW_LOCAL__?.token)&&document.getElementById('copperLab')?.hidden===false");
 if(ready)break;
 await new Promise(resolve=>setTimeout(resolve,100));
}
pass(ready,'native guarded copper GUI appears only with authenticated localhost service');
const dom=await cmd('DOM.getDocument',{depth:1});
const input=await cmd('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#copperZip'});
pass(!!input.nodeId,'portable KiCad ZIP picker is present');
await cmd('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[zip]});
await evaluate("document.getElementById('copperInspectForm').requestSubmit();true");
let inspected={};
for(let i=0;i<360;i++){
 inspected=await evaluate("(()=>({status:document.getElementById('copperStatus').textContent,inspectionRunning:document.getElementById('copperInspectRun').disabled,formHidden:document.getElementById('copperRouteForm').hidden,count:document.querySelectorAll('#copperPair option').length,options:[...document.querySelectorAll('#copperPair option')].map(x=>x.textContent)}))()");
 if(!inspected.formHidden)break;
 if(!inspected.inspectionRunning)throw Error('Browser native copper inspection rejected: '+inspected.status);
 await new Promise(resolve=>setTimeout(resolve,200));
}
pass(!inspected.formHidden&&inspected.count===37&&inspected.status.includes('16 physical DRC')&&inspected.status.includes('0 schematic-parity'),
 'browser selects real native KiCad unconnected pad UUID pairs; 37 open, 16 physical, 0 parity');
const index=inspected.options.findIndex(label=>viaMode
 ? label.includes('Pad 2 [GND] of R3')&&label.includes('Pad 2 [GND] of R4')
 : label.includes('Pad 2 [VCC_3V3] of U1')&&label.includes('Pad 3 [VCC_3V3] of U1'));
pass(index>=0,viaMode?'native exact R3.2↔R4.2 candidate':'native exact U1.2↔U1.3 electrical candidate exposed by real KiCad');
if(viaMode&&!batchMode){
 await evaluate("document.getElementById('copperPair').value="+JSON.stringify(String(index))+
  ";document.getElementById('copperWaypoints').value='[[72.51,58.8],[77.51,58.8]]';"+
  "document.getElementById('copperViaIndices').value='[1,1]';"+
  "document.getElementById('copperRouteForm').requestSubmit();true");
 let rejected=false;
 for(let attempt=0;attempt<25;attempt++){
  rejected=await evaluate("document.getElementById('copperStatus').textContent.includes('Via indices:')&&"+
    "document.getElementById('copperResult').hidden&&"+
    "!document.getElementById('copperRouteRun').disabled");
  if(rejected)break;
  await new Promise(resolve=>setTimeout(resolve,90));
 }
 pass(rejected,'Chrome rejects repeated/ambiguous through-via indices before launching a native job');
}
if(batchMode){
 pass(viaMode,'batch Chrome acceptance begins with explicit 2-via GND route');
 await evaluate("document.getElementById('copperPair').value="+JSON.stringify(String(index))+
  ";document.getElementById('copperWaypoints').value='[[72.51,58.8],[77.51,58.8]]';"+
  "document.getElementById('copperViaIndices').value='[1,2]';"+
  "document.getElementById('copperQueueAdd').click();true");
 const next=inspected.options.findIndex(label=>label.includes('Pad 2 [VCC_3V3] of U1')&&
  label.includes('Pad 3 [VCC_3V3] of U1'));
 pass(next>=0,'native VCC_3V3 second distinct electrical net is discoverable');
 await evaluate("document.getElementById('copperPair').value="+JSON.stringify(String(next))+
  ";document.getElementById('copperPair').dispatchEvent(new Event('change'));"+
  "document.getElementById('copperQueueAdd').click();true");
 pass(await evaluate("document.querySelectorAll('#copperQueued li').length===2&&"+
  "!document.getElementById('copperBatchRun').disabled"),
  'two real distinct nets with exact native pad UUIDs queued in browser');
 await evaluate("document.getElementById('copperBatchRun').click();true");
}else{
 await evaluate("document.getElementById('copperPair').value="+JSON.stringify(String(index))+
  (viaMode?";document.getElementById('copperWaypoints').value='[[72.51,58.8],[77.51,58.8]]';document.getElementById('copperViaIndices').value='[1,2]'":"")+
  ";document.getElementById('copperRouteForm').requestSubmit();true");
}
let result={};
for(let i=0;i<440;i++){
 result=await evaluate("(()=>({status:document.getElementById('copperStatus').textContent,running:document.getElementById('copperRouteRun').disabled,ready:!document.getElementById('copperResult').hidden,title:document.getElementById('copperResultTitle').textContent,summary:document.getElementById('copperResultSummary').textContent}))()");
 if(result.ready)break;
 if(!result.running&&!result.ready)throw Error('Native KiCad copper route rejected: '+result.status);
 await new Promise(resolve=>setTimeout(resolve,200));
}
console.log('CHROME_NATIVE_COPPER_VERIFICATION_STATE',JSON.stringify({result,viaMode,customMode,batchMode}));
pass(result.ready&&result.summary.includes(batchMode?'Unconnected: 37 → 35':'Unconnected: 37 → 36')&&
 result.summary.includes('Physical DRC: 16 → 16')&&
 (batchMode?result.title.includes('2 native links'):result.summary.includes('0.20 mm width'))&&
 result.title.includes('NOT APPROVED')&&
 (!customMode||batchMode||result.summary.includes('Custom .kicad_dru loader proof + independent default KiCad DRC passed'))&&
 (!viaMode||batchMode||(result.title.includes('2 through-via(s)')&&result.summary.includes('F.Cu → B.Cu → F.Cu'))),
 batchMode?'Chrome native multi-net transaction 37→35, 16→16 native DRC and explicit no-fab result':
 viaMode?'Chrome native F/B two-through-via copy proved DRC 37→36 without new violations and explicitly blocked fab':
 'Chrome native selected copper route reduced open count without new physical DRC; fabrication explicitly blocked');
let preview='';
for(let i=0;i<140;i++){
 preview=await evaluate("document.getElementById('copperPreview').srcdoc||''");
 if(preview.includes('BEFORE · original copper copy')&&preview.includes('AFTER · guarded route copy'))break;
 await new Promise(resolve=>setTimeout(resolve,100));
}
console.log('NATIVE_KICAD_PREVIEW_STATE',await evaluate("document.getElementById('copperStatus').textContent"),preview.length);
pass(preview.includes('BEFORE · original copper copy')&&preview.includes('AFTER · guarded route copy')&&
 preview.includes('NOT FABRICATION APPROVED')&&preview.match(/data:image\/svg\+xml;base64,/g)?.length===2,
 'Chrome displays two genuine native KiCad F.Cu pre/post SVG plots, not fake drawing');
await cmd('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await evaluate("(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,form:document.getElementById('copperRouteForm').getBoundingClientRect().toJSON(),result:document.getElementById('copperResult').getBoundingClientRect().toJSON()}))()");
pass(mobile.width<=390&&mobile.scroll<=390&&mobile.form.left>=0&&mobile.form.right<=390&&mobile.result.right<=390,
 '390px mobile Chrome native copper workflow has no horizontal overflow');
await mkdir(dir,{recursive:true});
await cmd('Page.setDownloadBehavior',{behavior:'allow',downloadPath:dir});
for(const [name,selector] of [['native-copper-project.zip','copperDownload'],['EVIDENCE.json','copperEvidence']]){
 await evaluate('document.getElementById('+JSON.stringify(selector)+').click();true');
 let bytes=null;
 for(let i=0;i<100;i++){
  const names=await readdir(dir);
  if(names.includes(name)&&!names.some(x=>x.endsWith('.crdownload'))){bytes=await readFile(path.join(dir,name));break;}
  await new Promise(resolve=>setTimeout(resolve,130));
 }
 pass(bytes!==null&&(name.endsWith('.zip')?bytes.subarray(0,2).toString()==='PK':
 (batchMode?JSON.parse(bytes.toString()).cumulative_drc.after_unconnected===35:
 JSON.parse(bytes.toString()).native_drc.after_unconnected===36)),
  'real Chrome downloaded authenticated private '+name+' with native KiCad DRC proof');
}
await evaluate("document.getElementById('copperDiscard').click();true");
let discarded=false;
for(let i=0;i<70;i++){
 discarded=await evaluate("document.getElementById('copperResult').hidden&&document.getElementById('copperStatus').textContent.includes('discarded')");
 if(discarded)break;
 await new Promise(resolve=>setTimeout(resolve,150));
}
pass(discarded,'Chrome discard removes only the isolated native copper draft');
const finalSha=createHash('sha256').update(await readFile(zip)).digest('hex');
pass(initialSha===finalSha,'original uploaded local project ZIP bytes never mutated');
pass(jsErrors.length===0,'zero runtime Chrome JavaScript errors: '+jsErrors.join(' / '));
ws.close();
console.log('GUARDED NATIVE COPPER CHROME: ALL PASSED');
