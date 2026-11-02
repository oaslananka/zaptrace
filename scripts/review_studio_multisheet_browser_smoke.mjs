// Actual native KiCad two-page Eeschema browser flow; read-only and fail closed.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9942);
const emptyRoot=process.env.ZAPTRACE_EMPTY_ROOT==='1';
const captureDir=process.env.ZAPTRACE_MULTISHEET_SCREEN_DIR||'build/native-multi-sheet-test';
let pages;
for(let i=0;i<75;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
const tab=pages?.find(p=>p.type==='page');if(!tab)throw Error('Real Chrome page not loaded');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let id=0;const pending=new Map(),exceptions=[];
ws.addEventListener('message',e=>{const r=JSON.parse(e.data);
 if(r.method==='Runtime.exceptionThrown')exceptions.push(r.params.exceptionDetails.text);
 if(r.id&&pending.has(r.id)){pending.get(r.id)(r);pending.delete(r.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const n=++id;pending.set(n,r=>r.error?rej(Error(JSON.stringify(r.error))):res(r.result));ws.send(JSON.stringify({id:n,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async x=>{const r=await call('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,msg)=>{if(!v)throw Error('FAIL '+msg);console.log('PASS',msg);};
const initial=await js(`(()=>({pages:DATA.schematic.pages.map(x=>({name:x.name,viewbox:x.viewbox,source:x.src.slice(0,26)})),
 referenced:DATA.schematic_hierarchy.page_count,net:DATA.net_parity.state,
 pin:DATA.pin_parity.state,reported:DATA.erc.count,open:DATA.open_pairs.length,
 dropdown:document.getElementById('schematicPagePicker').options.length,
 rootOnly:DATA.schematic.root_only}))()`);
check(initial.pages.length===2&&initial.referenced===2&&initial.pages[0].name==='Root sheet'&&
 initial.pages[1].name==='Power supply'&&initial.pages[0].source.includes('image/svg+xml')&&
 initial.rootOnly&&initial.net==='root_only_not_verified'&&initial.pin==='not_checked'&&
 initial.reported===28&&initial.open===12&&initial.dropdown===2,
 'two real native KiCad sheet pages are indexed without declaring hierarchical pad/net parity');
const root=await js(`(()=>{document.getElementById('modeSch').click();
 return {mode,visible:!document.getElementById('schematicPageNav').hidden,
 page:schematicPageIndex,refCount:schematicStage.querySelectorAll('.sch-hit').length,
 pinCount:schematicStage.querySelectorAll('.sch-pin-hit').length,
 original:schematicStage.querySelector('img').src};})()`);
check(root.mode==='schematic'&&root.visible&&root.page===0&&
 (emptyRoot?(root.refCount===0&&root.pinCount===0):(root.refCount>0&&root.pinCount>0)),
 'root sheet opens with authentic symbol/pin anchors, native page picker and KiCad-rendered SVG');
const child=await js(`(()=>{const picker=document.getElementById('schematicPagePicker');
 picker.value='1';picker.dispatchEvent(new Event('change',{bubbles:true}));
 return {page:schematicPageIndex,name:document.getElementById('canvasName').textContent,
 updated:schematicStage.querySelector('img').src!==DATA.schematic.pages[0].src,
 width:schematicStage.getBoundingClientRect().width,
 invisible:[...schematicStage.querySelectorAll('.sch-hit,.sch-pin-hit')].every(x=>x.hidden),
 trueDims:DATA.schematic.viewbox,notice:document.getElementById('schematicPageNote').textContent,
 fab:document.querySelector('.headside').textContent,
 drc:document.getElementById('kpiDrc').textContent,
 stored:JSON.parse(localStorage.getItem(PREF_KEY)).page};})()`);
check(child.page===1&&child.name.includes('Power supply')&&child.updated&&child.invisible&&
 child.trueDims[0]<300&&child.notice.includes('Root-only PCB cross-probe disabled')&&
 child.fab.includes('NOT FABRICATION APPROVED')&&child.drc==='16'&&child.stored===1,
 'child page displays source SVG and sheet dimensions, hides root-only hits, retains fab blocker and saves page');
const image=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(captureDir+'/professional-child-sheet.png',Buffer.from(image.data,'base64'));
await call('Page.reload',{ignoreCache:true});
let restored=null;
for(let i=0;i<60;i++){
 try{restored=await js(`(()=>({loaded:prefsReady,mode,page:schematicPageIndex,
  hidden:[...schematicStage.querySelectorAll('.sch-hit,.sch-pin-hit')].every(x=>x.hidden),
  src:schematicStage.querySelector('img').src===DATA.schematic.pages[1].src}))()`);
  if(restored.loaded)break;
 }catch{}
 await new Promise(r=>setTimeout(r,100));
}
check(restored?.loaded&&restored.mode==='schematic'&&restored.page===1&&restored.hidden&&restored.src,
 'page reload restores actual child-sheet preview without enabling unverified cross-probing');
const cross=await js(`(()=>{const result=focusSchematic('U1');return {result,page:schematicPageIndex,
 rootImage:schematicStage.querySelector('img').src===DATA.schematic.pages[0].src,
 markers:[...schematicStage.querySelectorAll('.sch-hit')].some(x=>!x.hidden),
 fab:document.querySelector('.headside').textContent};})()`);
check((emptyRoot?(!cross.result&&cross.page===1&&!cross.markers):
 (cross.result===true&&cross.page===0&&cross.rootImage&&cross.markers))&&
 cross.fab.includes('NOT FABRICATION APPROVED'),
 'cross-probe accepts only actual root symbols, refusing to hallucinate child symbol positions');
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{document.getElementById('schematicPagePicker').value='1';
 document.getElementById('schematicPagePicker').dispatchEvent(new Event('change'));
 const box=document.getElementById('schematicPagePicker').getBoundingClientRect();
 return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 picker:box.width,selected:schematicPageIndex,hidden:[...schematicStage.querySelectorAll('.sch-hit')].every(x=>x.hidden)};})()`);
check(mobile.width<=390&&mobile.scroll<=mobile.width&&mobile.picker>120&&mobile.selected===1&&mobile.hidden,
 '390px mobile sheet chooser remains usable with safe read-only child-page rendering');
await call('Emulation.clearDeviceMetricsOverride');
check(exceptions.length===0,'zero Chrome JavaScript exceptions in multi-sheet navigation');
await js(`localStorage.removeItem(PREF_KEY)`);
ws.close();console.log('TWO-PAGE NATIVE KiCad SCHEMATIC BROWSER: ALL PASSED');
