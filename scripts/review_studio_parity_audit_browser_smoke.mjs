// Real Chrome: source-only native schematic/PCB association with no synchronization.
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const sch=process.env.ZAPTRACE_PARITY_SCHEMATIC;
const pcb=process.env.ZAPTRACE_PARITY_PCB;
if(!port||!sch||!pcb)throw Error('Native schematic+board and real Chrome port are required');
let pages=[];
for(let i=0;i<90;i++){
 try{pages=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();if(pages.some(x=>x.type==='page'))break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,110));
}
const tab=pages.find(x=>x.type==='page'&&x.url?.startsWith('http://127.0.0.1:'))||pages.find(x=>x.type==='page');
if(!tab)throw Error('Chrome native workspace not found');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let id=0;
const pending=new Map(),errors=[];
ws.addEventListener('message',ev=>{
 const r=JSON.parse(ev.data);
 if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);
 if(r.id&&pending.has(r.id)){pending.get(r.id)(r);pending.delete(r.id);}
});
const cmd=(method,params={})=>new Promise((resolve,reject)=>{
 const i=++id;pending.set(i,r=>r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result));
 ws.send(JSON.stringify({id:i,method,params}));
});
await cmd('Runtime.enable');await cmd('Page.enable');await cmd('DOM.enable');
const evaluate=async expression=>{
 const r=await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
 if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
 return r.result.value;
};
const pass=(ok,label)=>{if(!ok)throw Error('FAIL '+label);console.log('PASS '+label);};
let ready=false;
for(let i=0;i<70;i++){
 ready=await evaluate("document.readyState==='complete'&&window.__REVIEW_LOCAL__?.token&&!document.getElementById('pcbAuditLab').hidden");
 if(ready)break;
 await new Promise(r=>setTimeout(r,100));
}
pass(ready,'authenticated local-only native schematic/PCB audit visible; standalone offline remains read-only');
const dom=await cmd('DOM.getDocument',{depth:1});
for(const [selector,source] of [['#pcbAuditSch',sch],['#pcbAuditPcb',pcb]]){
 const element=await cmd('DOM.querySelector',{nodeId:dom.root.nodeId,selector});
 pass(!!element.nodeId,selector+' native source selector exists');
 await cmd('DOM.setFileInputFiles',{nodeId:element.nodeId,files:[source]});
}
await evaluate("document.getElementById('pcbAuditForm').requestSubmit();true");
let result={};
for(let i=0;i<320;i++){
 result=await evaluate("(()=>({status:document.getElementById('pcbAuditStatus').textContent,working:document.getElementById('pcbAuditRun').disabled,visible:!document.getElementById('pcbAuditResult').hidden,summary:document.getElementById('pcbAuditSummary').textContent,differences:[...document.querySelectorAll('#pcbAuditDifferences li')].map(x=>x.textContent),linkage:document.getElementById('pcbAuditLinkage').textContent}))()");
 if(result.visible)break;
 if(!result.working&&!result.visible)throw Error('Browser parity API refused: '+result.status);
 await new Promise(r=>setTimeout(r,100));
}
console.log('NATIVE SCHEMATIC PCB AUDIT',result);
pass(result.visible&&result.summary.includes('Schematic: 14')&&result.summary.includes('PCB: 14')&&result.summary.includes('field discrepancies: 5'),
 'native KiCad compares 14 real components and flags five actual value mismatches');
pass(result.differences.length===5&&['J1','TP1','TP2','U2','U3'].every(ref=>result.differences.some(line=>line.startsWith(ref+' · value'))),
 'five specific source-backed mismatches displayed with no fabricated connectivity');
pass(result.linkage.includes('UUID linkage verified: NO')&&result.linkage.includes('Automatic sync: BLOCKED')&&result.linkage.includes('NOT APPROVED'),
 'browser explicitly refuses UUID, net, electrical or fabrication parity authorization');
await cmd('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await evaluate("(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,form:document.getElementById('pcbAuditForm').getBoundingClientRect().toJSON(),result:document.getElementById('pcbAuditResult').getBoundingClientRect().toJSON()}))()");
pass(mobile.width<=390&&mobile.scroll<=390&&mobile.form.left>=0&&mobile.form.right<=390&&mobile.result.right<=390,
 '390px Chrome native audit is responsive and has no page horizontal overflow');
pass(errors.length===0,'zero Chrome JavaScript errors during native read-only audit: '+errors.join(','));
ws.close();console.log('NATIVE SCHEMATIC PCB PARITY CHROME: ALL PASSED');
