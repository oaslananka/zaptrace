// Native two-snapshot source comparison, actual Chrome UI interactions.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||10551);
const shots=process.env.ZAPTRACE_WORKSPACE_SCREENSHOTS||'build/review-studio-workspace';
let pages;
for(let i=0;i<60;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,140));
}
const page=pages?.find(p=>p.type==='page');if(!page)throw Error('Chrome comparison page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true});});
let seq=0;const pending=new Map(),errors=[];
ws.addEventListener('message',ev=>{const r=JSON.parse(ev.data);
 if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);
 if(r.id&&pending.has(r.id)){pending.get(r.id)(r);pending.delete(r.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const id=++seq;pending.set(id,r=>r.error?rej(Error(JSON.stringify(r.error))):res(r.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async code=>{const r=await call('Runtime.evaluate',{expression:code,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(c,msg)=>{if(!c)throw Error('FAIL '+msg);console.log('PASS '+msg);};
let loaded=false;
for(let i=0;i<80;i++){
 try{loaded=await js(`document.readyState==='complete'&&!!document.getElementById('comparePanel')&&document.querySelectorAll('.project').length>=2`);if(loaded)break;}catch{}
 await new Promise(r=>setTimeout(r,95));
}
check(loaded,'local app and real source cards have rendered before Chrome interaction');
const data=await js(`(()=>({cards:document.querySelectorAll('.project').length,
 options:document.querySelectorAll('.compare-checkbox').length,
 sources:[...document.querySelectorAll('.project')].map(x=>({name:x.querySelector('h3').textContent,copper:x.dataset.copper,open:x.dataset.open,rule:x.dataset.ruleFindings,lib:x.dataset.libraryFindings,project:x.dataset.projectRules})),
 hidden:document.getElementById('comparePanel').hidden,gate:document.querySelector('header .gate').textContent}))()`);
console.log('NATIVE COMPARE RAW BOARD EVIDENCE',data);
check(data.cards>=2&&data.options===data.cards&&data.hidden&&data.gate.includes('NOT FABRICATION APPROVED'),
 'compare is hidden until exactly two source-verified local snapshots selected');
const chosen=await js(`(()=>{
 const items=[...document.querySelectorAll('.project')];
 items[0].querySelector('.compare-checkbox').click();
 const before={hidden:document.getElementById('comparePanel').hidden,status:document.getElementById('compareSelection').textContent};
 items[1].querySelector('.compare-checkbox').click();
 return {before,hidden:document.getElementById('comparePanel').hidden,
 selection:document.getElementById('compareSelection').textContent,
 warning:document.getElementById('compareContext').textContent,
 metrics:[...document.querySelectorAll('.compare-metric')].map(x=>({title:x.querySelector('.compare-metric-title').textContent,
  numbers:[...x.querySelectorAll('strong')].map(y=>y.textContent),diff:x.querySelector('.compare-metric-values span').textContent})),
 links:[...document.querySelectorAll('.compare-links a')].map(a=>({href:a.href,text:a.textContent})),
 sha:[...document.querySelectorAll('.compare-side p')].map(p=>p.textContent),
 classes:[...items].map(x=>x.classList.contains('compare-active'))};})()`);
console.log('CHROME VERIFIED DIFFERENCE',chosen);
check(chosen.before.hidden&&chosen.before.status.includes('1 of 2')&&!chosen.hidden&&chosen.selection.includes('2 of 2')&&
 chosen.classes.slice(0,2).every(Boolean)&&chosen.classes.slice(2).every(x=>!x),
 'native project selections update visual state and only reveal comparison when exactly two checked');
check(chosen.warning.includes('DIFFERENT KICAD RULE CONTEXTS')&&chosen.warning.includes('NOT an apples-to-apples manufacturability comparison'),
 'different original .kicad_pro contexts trigger a mandatory clear DRC comparability warning');
const byTitle=Object.fromEntries(chosen.metrics.map(x=>[x.title,x]));
check(byTitle['Copper items']?.numbers.join(',')==='61,0'&&byTitle['Copper items']?.diff.includes('-61')&&
 byTitle['Open connections']?.numbers.join(',')==='12,37'&&byTitle['Open connections']?.diff.includes('+25')&&
 byTitle['PCB rule findings']?.numbers.join(',')==='16,28'&&
 byTitle['Library findings']?.numbers.join(',')==='0,14'&&
 byTitle['Schematic ERC']?.numbers.join(',')==='0,0',
 'native comparison uses real 61 vs 0 copper items, 12 vs 37 open items, and exact PCB rule counts');
check(chosen.links.length===4&&chosen.links.every(x=>x.href.includes('index.html')||x.href.includes('REVIEW_REPORT.html')),
 'both source-specific read-only engineering reviews and their evidence reports are navigable');
if(data.cards>2){
 const denied=await js(`(()=>{const third=[...document.querySelectorAll('.project')][2].querySelector('.compare-checkbox');
  third.click();
  return {checked:third.checked,status:document.getElementById('compareSelection').textContent,
   selections:[...document.querySelectorAll('.compare-checkbox')].filter(x=>x.checked).length,
   metric:document.querySelector('.compare-metric-values')?.textContent};})()`);
 check(!denied.checked&&denied.selections===2&&denied.status.includes('Maximum two snapshots')&&
 denied.metric?.includes('61'),
 'third native source cannot overwrite existing two-snapshot comparison or make a misleading triple-delta');
}
const picture=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/professional-evidence-comparison-desktop.png',Buffer.from(picture.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{const p=document.getElementById('comparePanel');p.scrollIntoView({block:'start'});
 return {viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 panel:p.getBoundingClientRect().width,cols:getComputedStyle(document.querySelector('.compare-designs')).gridTemplateColumns,
 cards:getComputedStyle(document.querySelector('.compare-metrics')).gridTemplateColumns,
 warning:document.getElementById('compareContext').textContent.includes('DIFFERENT KICAD RULE CONTEXTS'),
 selection:[...document.querySelectorAll('.compare-checkbox')].filter(x=>x.checked).length,
 offenders:[...document.querySelectorAll('body *')].filter(x=>{const r=x.getBoundingClientRect();return r.right>394&&r.width>0&&getComputedStyle(x).position!=='absolute';}).slice(0,25).map(x=>({tag:x.tagName,css:x.className,parent:x.parentElement?.className,html:x.outerHTML.slice(0,320),scroll:x.scrollWidth,right:Math.round(x.getBoundingClientRect().right),width:Math.round(x.getBoundingClientRect().width)}))};})()`);
console.log('CHROME COMPARISON 390px',mobile);
check(mobile.viewport<=390&&mobile.scroll<=mobile.viewport&&mobile.panel<390&&mobile.warning&&mobile.selection===2,
 'comparison works at 390px without page overflow and preserves prominent DRC context warning');
const mobilePicture=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/professional-evidence-comparison-mobile.png',Buffer.from(mobilePicture.data,'base64'));
await call('Emulation.clearDeviceMetricsOverride');
const removed=await js(`(()=>{document.getElementById('compareClear').click();
 return {hidden:document.getElementById('comparePanel').hidden,checked:[...document.querySelectorAll('.compare-checkbox')].filter(x=>x.checked).length,
 status:document.getElementById('compareSelection').textContent,
 gate:document.querySelector('header .gate').textContent};})()`);
check(removed.hidden&&removed.checked===0&&removed.status.includes('Select two')&&removed.gate.includes('NOT FABRICATION APPROVED'),
 'clear resets all comparison state without changing fabrication authorization or underlying evidence');
check(errors.length===0,'no browser runtime exceptions in native source comparison');
ws.close();console.log('PROFESSIONAL NATIVE EVIDENCE COMPARISON: ALL CHROME TESTS PASSED');
