import {readFileSync,existsSync} from 'node:fs';
const p=+process.env.CDP_PORT,download=process.env.TRIAGE_DOWNLOAD;
if(!p||!download)throw Error('Missing owned browser configuration');
let data;
for(let i=0;i<100;i++){
 try {data=await(await fetch(`http://127.0.0.1:${p}/json/list`)).json();if(data.length)break;}catch{}
 await new Promise(r=>setTimeout(r,120));
}
const page=data.find(x=>x.type==='page'&&x.url?.includes('/index.html'));
if(!page)throw Error('Owned local source-bound viewer not available');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((yes,no)=>{ws.addEventListener('open',yes,{once:true});ws.addEventListener('error',no,{once:true});});
let seq=0,exceptions=[];const waits=new Map();ws.addEventListener('message',e=>{let r=JSON.parse(e.data);if(r.method==='Runtime.exceptionThrown')exceptions.push(r.params.exceptionDetails.text);if(r.id&&waits.has(r.id)){waits.get(r.id)(r);waits.delete(r.id);}});
const call=(method,params={})=>new Promise((yes,no)=>{const id=++seq;waits.set(id,r=>r.error?no(Error(JSON.stringify(r.error))):yes(r.result));ws.send(JSON.stringify({id,method,params}));});
const js=async(expression)=>{const res=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(res.exceptionDetails)throw Error(JSON.stringify(res.exceptionDetails));return res.result.value;};
const check=(cond,msg)=>{if(!cond)throw Error('EXACT_REAL_CHROME_TRIAGE_FAIL: '+msg);console.log('EXACT_REAL_CHROME_TRIAGE_PASS',msg);};
await call('Runtime.enable');await call('Page.enable');
let ready=false;
for(let tick=0;tick<150;tick++){
 const state=await js("({ready:document.readyState,source:typeof DATA,error:document.querySelector('script')?.textContent?.length})");
 if(state.ready==='complete'&&state.source==='object'){ready=true;break;}
 await new Promise(resolve=>setTimeout(resolve,100));
}
check(ready,'real local KiCad viewer finished JS initialization before UI assertions');
for(const width of [320,390,1440]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,mobile:width<768,deviceScaleFactor:1});
 const a=await js(`(()=>({sha:DATA.source_sha256,disabled:document.getElementById('exportTriage').disabled,total:DATA.findings.length,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,visible:!document.getElementById('triageProgress').closest('[hidden]')}))()`);
 check(a.sha==='fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce'&&a.disabled&&a.total>0&&a.overflow===0&&a.visible,`${width}px first-view read-only session journal and no overflow`);
}
await js("setTab('issues');select({kind:'issue',index:0},false)");
let x=await js(`(()=>({found:document.getElementById('triageOutcome')!==null,status:document.getElementById('triageOutcome').value,drccount:DATA.findings.length,exportDisabled:document.getElementById('exportTriage').disabled}))()`);
check(x.found&&x.status==='unreviewed'&&x.exportDisabled,'source DRC finding opens honest empty review editor');
await js(`(()=>{const o=document.getElementById('triageOutcome'),n=document.getElementById('triageNote');o.value='repair_required';n.value='<script>alert(1)</script> verify via dimensions';document.querySelector('.triage-editor button').click();})()`);
x=await js(`(()=>({note:triageNotes.get(0),status:document.getElementById('triageProgress').innerText,exportDisabled:document.getElementById('exportTriage').disabled,drccount:DATA.findings.length,htmlscript:document.querySelector('.triage-editor script')!==null}))()`);
for(const width of [320,390,1440]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,mobile:width<768,deviceScaleFactor:1});
 await js("document.querySelector('.triage-editor button').scrollIntoView({block:'center'})");
 const layout=await js(`(()=>{const e=document.querySelector('.triage-editor button'),r=e.getBoundingClientRect(),d=e.closest('.detail');return {bounds:r.toJSON(),width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,detailMaxHeight:getComputedStyle(d).maxHeight,detailOverflow:getComputedStyle(d).overflowY}})()`);
 check(layout.bounds.left>=0&&layout.bounds.right<=width+1&&layout.scrollWidth<=width+1&&
   (width>750||(layout.detailMaxHeight==='none'&&layout.detailOverflow==='visible')),
   `${width}px triage form remains on-screen without horizontal overflow`);
 const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 const {writeFileSync}=await import('node:fs');
 writeFileSync(`${process.env.TRIAGE_SCREEN_DIR||"build/qa-020-prototype"}/triage-${width}.png`,Buffer.from(shot.data,'base64'));
}
check(x.note?.status==='repair_required'&&x.note.note.startsWith('<script>')&&x.status.includes('need repair')&&!x.exportDisabled&&!x.htmlscript&&x.drccount>0,'repair-required note remains inert text and source DRC unchanged');
check(await js("document.getElementById('entrylist').innerText.includes('REVIEW NOTE: repair required')"),'repair status is visually discoverable in native KiCad DRC finding list');
await js("select({kind:'issue',index:1},false)");
await js(`(()=>{document.getElementById('triageOutcome').value='investigated';document.getElementById('triageNote').value='Check pad selection manually';document.querySelector('.triage-editor button').click();})()`);
const expected=await js('exportableTriage()');
check(expected.notes.length===2&&expected.source_sha256==='fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce'&&expected.all_findings_remain_unwaived&&expected.fabrication_approved===false&&expected.source_modified===false&&expected.notes.map(x=>x.triage).join(',')==='repair_required,investigated','export ties two human notes to immutable KiCad SHA without waiving DRC');
await call('Page.setDownloadBehavior',{behavior:'allow',downloadPath:download});
await js("downloadTriage()");
const filename=download+'/zaptrace-review-notes-fb3a0acbcafcdfe2.json';
for(let i=0;i<40&&!existsSync(filename);i++)await new Promise(r=>setTimeout(r,100));
check(existsSync(filename),'real Chrome downloads source-hash-bound JSON journal');
const parsed=JSON.parse(readFileSync(filename,'utf-8'));
check(JSON.stringify(parsed)===JSON.stringify(expected),'browser-exported JSON byte content matches on-screen review statuses and real source records');
await call('Page.reload',{ignoreCache:true});await new Promise(r=>setTimeout(r,350));
const reset=await js('({count:triageNotes.size,downloadDisabled:document.getElementById("exportTriage").disabled,source:DATA.source_sha256})');
check(reset.count===0&&reset.downloadDisabled&&reset.source===expected.source_sha256,'new browser load fails closed to zero human notes (no stale approval or persistence)');
await call('DOM.enable');
const doc=await call('DOM.getDocument');
const input=await call('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#triageFile'});
check(Boolean(input.nodeId),'native file input for re-importing source-matched notes exists');
await call('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[filename]});
for(let wait=0;wait<80;wait++){
 if(await js('triageNotes.size')===2)break;
 await new Promise(resolve=>setTimeout(resolve,50));
}
const restored=await js('triageNotes.size');
check(await js("document.getElementById('triageImportStatus').textContent.includes('source-matched human notes imported')"),
  'real Chrome file input dispatches native import and announces restored notes');
check(restored===2&&await js('triageNotes.size')===2,'valid source-matched exported note file safely restores previous session');
const badSha=structuredClone(expected);badSha.source_sha256='0'.repeat(64);
const mismatch=await js(`(async()=>{try{await readTriageFile(new File([${JSON.stringify(JSON.stringify(badSha))}],'wrong-source.json',{type:'application/json'}));return 'accepted';}catch(e){return e.message}})()`);
check(mismatch.includes('Different source')&&await js('triageNotes.size')===2,'wrong source SHA is rejected atomically without changing current notes');
const badRecord=structuredClone(expected);badRecord.notes[0].message='fake-approved-finding';
const altered=await js(`(async()=>{try{await readTriageFile(new File([${JSON.stringify(JSON.stringify(badRecord))}],'tampered.json',{type:'application/json'}));return 'accepted';}catch(e){return e.message}})()`);
check(altered.includes('different original KiCad finding')&&await js('triageNotes.size')===2,'tampered finding details rejected before restoring any state');
const dupe=structuredClone(expected);dupe.notes[1].finding_index=dupe.notes[0].finding_index;
const duplicate=await js(`(async()=>{try{await readTriageFile(new File([${JSON.stringify(JSON.stringify(dupe))}],'dupe.json',{type:'application/json'}));return 'accepted';}catch(e){return e.message}})()`);
check(duplicate.includes('duplicate')&&await js('triageNotes.size')===2,'duplicate finding IDs rejected without partial mutation');
check(exceptions.length===0,'zero Chrome JavaScript exceptions');
ws.close();console.log('STAGED_020_NATIVE_KICAD_SESSION_TRIAGE_E2E=PASS');
