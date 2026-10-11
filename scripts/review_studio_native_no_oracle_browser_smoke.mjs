// Offline negative smoke: no DRC/schematic means unknown, never a green sign-off.
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9430);
let pages;
for(let i=0;i<50;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}
 catch{}await new Promise(r=>setTimeout(r,130));
}
const page=pages?.find(p=>p.type==='page');if(!page)throw Error('Local Chrome page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true});});
let seq=0;const pending=new Map();
ws.addEventListener('message',e=>{const v=JSON.parse(e.data);if(v.id&&pending.has(v.id)){pending.get(v.id)(v);pending.delete(v.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{let id=++seq;pending.set(id,v=>v.error?reject(Error(JSON.stringify(v.error))):resolve(v.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');
const probe=await call('Runtime.evaluate',{expression:`(()=>{const $=x=>document.getElementById(x);
 $('quickDrc').click();const issues=$('entrylist').textContent;
 $('quickOpen').click();const opens=$('entrylist').textContent;
 return {drc:$('kpiDrc').textContent,open:$('kpiOpens').textContent,
 erc:$('kpiErc').textContent,pins:$('kpiPins').textContent,
 disabled:$('quickErc').disabled,issues,opens,status:document.querySelector('header .statuspill:not(.localpill)').textContent,
 report:$('evidenceReport').getAttribute('href'),error:typeof DATA.schematic==='object'&&DATA.schematic===null};})()`,returnByValue:true});
const v=probe.result.value;
if(v.drc!=='—'||v.open!=='—'||v.erc!=='—'||v.pins!=='—'||!v.disabled||!v.error||
 !v.issues.includes('not run')||
 !v.opens.includes('not run')||!v.status.includes('NOT FABRICATION APPROVED')||v.report!=='REVIEW_REPORT.html'){
 throw Error('Fail-closed UI gate regression: '+JSON.stringify(v));
}
console.log('PASS NO-ORACLE LOCAL BROWSER: DRC/opens/ERC/pin map unknown, schematic action disabled, fabrication blocked');
const commandProbe=await call('Runtime.evaluate',{expression:`(()=>{
 document.getElementById('searchCanvas').click();
 const types=commandItems.reduce((acc,x)=>(acc[x.kind]=(acc[x.kind]||0)+1,acc),{});
 const input=document.getElementById('commandInput');
 input.value='J1.A5';input.dispatchEvent(new Event('input'));
 const selected=document.querySelector('.command-result');
 const real=selected?.querySelector('.command-type')?.textContent==='PAD';
 const count=document.querySelectorAll('.command-result').length;
 const text=selected?.textContent;
 document.getElementById('closeCommand').click();
 return {types,real,count,text,closed:document.getElementById('commandBackdrop').hidden,
  drc:document.getElementById('kpiDrc').textContent};})()`,returnByValue:true});
const c=commandProbe.result.value;
if(c.types.DRC||c.types.OPEN||c.types.SCH||c.types.PAD!==112||c.types.PART!==14||
 !c.real||c.count!==1||!c.text.includes('J1.A5')||!c.closed||c.drc!=='—'){
 throw Error('No-oracle command palette must never invent DRC, open pairs or schematic pins: '+JSON.stringify(c));
}
console.log('PASS NO-ORACLE COMMAND: native pads browsable; DRC, open pairs and schematic pins not invented');
const reviewQueue=await call('Runtime.evaluate',{expression:`(()=>{const $=id=>document.getElementById(id);
 $('quickDrc').click();const drcHidden=$('reviewQueue').hidden;
 const ignored=advanceReview(1);
 $('quickOpen').click();const openHidden=$('reviewQueue').hidden;
 return {drcHidden,openHidden,ignored,selection:selected,errors:DATA.findings.length};})()`,returnByValue:true});
const q=reviewQueue.result.value;
if(!q.drcHidden||!q.openHidden||q.ignored||q.errors!==0||q.selection!==null)
 throw Error('Native review queue cannot invent disconnected or DRC findings: '+JSON.stringify(q));
console.log('PASS NO-ORACLE QUEUE: review navigation disabled; no invented native DRC findings');

ws.close();
