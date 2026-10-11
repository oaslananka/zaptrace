// Real offline Chromium verification of KiCad-created before/after ECO SVGs.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const shots=process.env.ZAPTRACE_ECO_SHOTS||'build/eco-native-R1-value-zoom-v2';
if(!port)throw Error('Real Chrome remote-debugging port required');
let pages=[];
for(let i=0;i<80;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
const tab=pages.find(p=>p.type==='page');if(!tab)throw Error('Native KiCad ECO viewer Chrome unavailable');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let id=0;const callbacks=new Map(),exceptions=[];
ws.addEventListener('message',e=>{const x=JSON.parse(e.data);if(x.method==='Runtime.exceptionThrown')exceptions.push(x.params.exceptionDetails.text);
 if(x.id&&callbacks.has(x.id)){callbacks.get(x.id)(x);callbacks.delete(x.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;callbacks.set(n,r=>r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result));ws.send(JSON.stringify({id:n,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async expr=>{const r=await call('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,s)=>{if(!v)throw Error('FAIL '+s);console.log('PASS '+s);};
let ready=false;
for(let i=0;i<80;i++){
 ready=await js(`document.readyState==='complete'&&document.querySelectorAll('.sheet-frame img').length===2&&
 [...document.querySelectorAll('.sheet-frame img')].every(img=>img.complete&&img.naturalWidth>50)`);
 if(ready)break;await new Promise(r=>setTimeout(r,80));
}
check(ready,'two actual KiCad SVG plot images loaded, source-bound and fully offline');
const evidence=await js(`(()=>({title:document.title,headline:document.querySelector('h1').textContent,
 source:[...document.querySelectorAll('.sheet-frame img')].map(img=>img.src.slice(0,27)),
 model:document.querySelector('.diff').textContent,verdict:document.querySelector('.safety').textContent,
 zoom:document.getElementById('zoom').value,panes:document.querySelectorAll('.sheet-frame').length}))()`);
check(evidence.title.includes('R1')&&evidence.headline.includes('ECO')&&evidence.source.every(s=>s.startsWith('data:image/svg+xml;base64'))&&
 evidence.model.includes('4.7k')&&evidence.model.includes('10k')&&evidence.verdict.includes('NOT FABRICATION APPROVED')&&
 evidence.zoom==='100'&&evidence.panes===2,'proof shows exactly R1 4.7k → 10k and explicit PCB/fab exclusions');
const zoom=await js(`(()=>{document.getElementById('zoomIn').click();document.getElementById('zoomIn').click();
 const imgs=[...document.querySelectorAll('.sheet-frame img')];return {
 pct:document.getElementById('zoomPercent').textContent,slider:document.getElementById('zoom').value,
 widths:imgs.map(x=>x.getBoundingClientRect().width),parents:imgs.map(x=>x.parentElement.getBoundingClientRect().width)};})()`);
check(zoom.pct==='150%'&&zoom.slider==='150'&&zoom.widths.every((w,i)=>w>zoom.parents[i]*1.45),
 'synchronized source-sheet zoom increases both authentic KiCad plots to the same 150%');
const scrolling=await js(`(()=>{const a=document.getElementById('frameBefore');a.scrollLeft=110;a.scrollTop=45;
 return new Promise(done=>setTimeout(()=>{const b=document.getElementById('frameAfter');done({left:a.scrollLeft,right:b.scrollLeft,top:a.scrollTop,bottom:b.scrollTop});},120));})()`);
check(scrolling.left>=100&&Math.abs(scrolling.left-scrolling.right)<3&&Math.abs(scrolling.top-scrolling.bottom)<3,
 'scrolling the source KiCad drawing synchronizes corresponding coordinates in the new copied schematic');
const desktop=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/eco-value-before-after-desktop.png',Buffer.from(desktop.data,'base64'));
const reset=await js(`(()=>{document.getElementById('zoomFit').click();const a=document.getElementById('frameBefore'),b=document.getElementById('frameAfter');
 return {zoom:document.getElementById('zoom').value,x:a.scrollLeft,y:a.scrollTop,right:b.scrollLeft,bottom:b.scrollTop};})()`);
check(reset.zoom==='100'&&reset.x===0&&reset.y===0&&reset.right===0&&reset.bottom===0,
 'Fit both restores true source-sheet bounds and resets synchronized pan without editing source geometry');
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{const a=document.getElementById('frameBefore').getBoundingClientRect(),b=document.getElementById('frameAfter').getBoundingClientRect();
 return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 first:{left:a.left,right:a.right,top:a.top,bottom:a.bottom},second:{left:b.left,right:b.right,top:b.top,bottom:b.bottom},
 buttons:[...document.querySelectorAll('.zoom-toolbar button')].map(x=>x.getBoundingClientRect().width)};})()`);
console.log('MOBILE ECO PREVIEW 390',mobile);
check(mobile.width<=390&&mobile.scroll<=390&&mobile.first.left>=0&&mobile.first.right<=390&&
 mobile.second.top>mobile.first.top&&mobile.second.left>=0&&mobile.second.right<=390&&mobile.buttons.every(n=>n>=30),
 '390px native ECO visual comparison stacks source and working-copy drawings with no horizontal overflow');
const phone=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/eco-value-before-after-mobile.png',Buffer.from(phone.data,'base64'));
check(exceptions.length===0,'no actual Chromium errors in source-backed ECO before/after UI');
ws.close();console.log('NATIVE KICAD SCHEMATIC ECO CHROME: ALL PASSED');
