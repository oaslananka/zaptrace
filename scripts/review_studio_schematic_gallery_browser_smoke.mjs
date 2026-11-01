// Real native KiCad SVG sheet gallery / canvas navigation / root-only scope.
// Uses the installed Chrome devtools protocol; never invokes an external CDN.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const kind=process.env.ZAPTRACE_GALLERY_KIND||'multi';
const out=process.env.ZAPTRACE_GALLERY_SHOTS||'build/native-multi-sheet-test';
if(!port||!['multi','single'].includes(kind))throw Error('Set Chrome port and multi/single native review mode');
let pages=[];
for(let i=0;i<100;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,110));
}
const tab=pages.find(p=>p.type==='page');if(!tab)throw Error('Real Chrome KiCad native preview unavailable');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const requests=new Map(),errors=[];
ws.addEventListener('message',ev=>{const item=JSON.parse(ev.data);if(item.method==='Runtime.exceptionThrown')errors.push(item.params.exceptionDetails.text);
 if(item.id&&requests.has(item.id)){requests.get(item.id)(item);requests.delete(item.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;requests.set(id,res=>res.error?reject(Error(JSON.stringify(res.error))):resolve(res.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async expr=>{const r=await call('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,msg)=>{if(!v)throw Error('FAIL '+msg);console.log('PASS '+msg);};
await js(`localStorage.clear()`);
await call('Page.reload',{ignoreCache:true});
let ready=false;
for(let i=0;i<75;i++){
 try{ready=await js(`document.readyState==='complete'&&prefsReady&&document.querySelectorAll('.sheet-thumb').length>0`);if(ready)break;}catch{}
 await new Promise(r=>setTimeout(r,130));
}
check(ready,'real KiCad gallery is rendered after native review boot, without invented thumbnails');
let thumbsReady=false;
for(let i=0;i<80;i++){
 thumbsReady=await js(`[...document.querySelectorAll('.sheet-thumb img')].every((im,index)=>
 index>=4||(im.complete&&im.naturalWidth>0))`);
 if(thumbsReady)break;
 await new Promise(r=>setTimeout(r,100));
}
check(thumbsReady,'first four original KiCad sheet thumbnails render promptly even in collapsed sidebars');
const initial=await js(`(()=>{const $=id=>document.getElementById(id),imgs=[...document.querySelectorAll('.sheet-thumb img')];
 return {count:imgs.length,pages:DATA.schematic.pages.length,correct:imgs.every((im,i)=>im.src===DATA.schematic.pages[i].src),
 source:imgs.every(im=>im.src.startsWith('data:image/svg+xml;base64,')),children:imgs.every(im=>im.complete&&im.naturalWidth>0),
 guard:$('schematicSheetDock').hidden, context:$('schematicPageNav').hidden,mode,
 approval:document.querySelector('header .headside').textContent.includes('NOT FABRICATION APPROVED')};})()`);
console.log('NATIVE SHEET GALLERY',initial);
check(initial.count===initial.pages&&initial.correct&&initial.source&&initial.children&&initial.guard&&initial.approval,
 'each page thumbnail is the actual native KiCad-rendered SVG, and inactive UI is hidden while in PCB mode');
check(initial.count===(kind==='multi'?2:1),'gallery has only actual physical KiCad sheet count');
const activated=await js(`(()=>{document.getElementById('modeSch').click();
 const $=id=>document.getElementById(id);
 return {mode,index:schematicPageIndex,dock:!$('schematicSheetDock').hidden,
 nav:!$('schematicPageNav').hidden,
 disabledPrev:$('schematicPrevious').disabled,disabledNext:$('schematicNext').disabled,
 focus:$('schematicFocusSymbols').disabled,rootSymbols:DATA.schematic.symbols?.length||0,
 active:[...document.querySelectorAll('.sheet-thumb')].map(b=>b.getAttribute('aria-current')),
 scope:$('schematicDockScope').textContent,approval:document.querySelector('header .headside').textContent};})()`);
check(activated.mode==='schematic'&&activated.index===0&&activated.nav&&activated.dock&&activated.disabledPrev&&activated.active[0]==='page',
 'opening read-only schematic shows branded side sheet gallery, readable canvas sheet dock and current page');
check(activated.focus===(activated.rootSymbols===0),'focus root components enabled only when the native source root has actual symbols');
const sourceRefs=await js(`(()=>({actual:DATA.schematic.crossprobe_refs,
 declared:DATA.schematic.symbols.map(s=>s.ref),
 listed:[...document.querySelectorAll('.sheet-ref')].map(b=>b.dataset.ref),
 sourceLinked:!document.getElementById('schematicReferencePanel').hidden}))()`);
check(sourceRefs.listed.every(ref=>sourceRefs.actual.includes(ref)&&sourceRefs.declared.includes(ref))&&
 sourceRefs.sourceLinked===(sourceRefs.listed.length>0),
 'quick-reference palette is sourced only from genuine KiCad symbols with authored PCB-reference links');
if(kind==='multi'){
 const next=await js(`(()=>{document.getElementById('schematicNext').click();return {
  index:schematicPageIndex,prev:document.getElementById('schematicPrevious').disabled,
  next:document.getElementById('schematicNext').disabled,
  active:[...document.querySelectorAll('.sheet-thumb')].map(b=>b.getAttribute('aria-current')),
  canvas:document.getElementById('schematicDockTitle').textContent,
  scope:document.getElementById('schematicDockScope').textContent,
  focus:document.getElementById('schematicFocusSymbols').disabled,
  matches:[...schematicStage.querySelectorAll('.sch-hit,.sch-pin-hit')].every(x=>x.hidden)};})()`);
 check(next.index===1&&!next.prev&&next.next&&next.active[1]==='page'&&next.active[0]==='false'&&
 next.canvas==='Power supply'&&next.scope.startsWith('Child')&&next.focus&&next.matches,
 'next sheet switches to native KiCad child page, disables root-only symbols and accurately scopes capabilities');
 const key=await js(`(()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'[',bubbles:true}));
 const back=schematicPageIndex;document.dispatchEvent(new KeyboardEvent('keydown',{key:']',bubbles:true}));
 return {back,forward:schematicPageIndex,dock:document.getElementById('schematicDockIndex').textContent};})()`);
 check(key.back===0&&key.forward===1&&key.dock==='SHEET 02 / 02',
 'keyboard [ and ] navigate only authentic KiCad pages and update exact sheet counter');
 const thumb=await js(`(()=>{document.querySelectorAll('.sheet-thumb')[0].click();return {
 index:schematicPageIndex,now:document.querySelector('.sheet-thumb[aria-current="page"]')?.title,
 image:schematicStage.querySelector('img').src===DATA.schematic.pages[0].src};})()`);
 check(thumb.index===0&&thumb.now?.includes('Root sheet')&&thumb.image,
 'clicking a real KiCad thumbnail selects root sheet and restores root SVG source');
}else{
 const fitResult=await js(`(()=>{const before={zoom,panX,panY};
 const ok=focusNativeRootSymbols();return {ok,before,zoom,panX,panY,
 symbols:DATA.schematic.symbols.length,source:schematicStage.querySelector('img').src===DATA.schematic.pages[0].src,
 report:document.getElementById('kpiDrc').textContent};})()`);
 console.log('SINGLE NATIVE FOCUS',fitResult);
 check(fitResult.ok&&fitResult.symbols>0&&fitResult.zoom>fitResult.before.zoom&&fitResult.source&&fitResult.report==='16',
 'focus button makes genuine Eeschema native root symbols readable without moving PCB tracks or altering DRC evidence');
 const reference=await js(`(()=>{const b=[...document.querySelectorAll('.sheet-ref')].find(btn=>btn.dataset.ref==='U1');
 if(!b)return {notFound:true};b.click();return {selected:b.getAttribute('aria-pressed'),
 page:schematicPageIndex,mode,panX,panY,marker:focusButtons.symbols.get('U1')?.classList.contains('selected'),
 title:document.querySelector('#detail h3')?.textContent,
 jump:document.querySelector('#detail .crossnav:last-child')?.textContent,
 fabricator:document.querySelector('header .headside').textContent};})()`);
 console.log('SOURCE-LINKED COMPONENT NAVIGATION',reference);
 check(reference.selected==='true'&&reference.page===0&&reference.mode==='schematic'&&reference.marker&&
  reference.title?.includes('U1')&&reference.jump?.includes('Go to native PCB footprint U1')&&
  reference.fabricator.includes('NOT FABRICATION APPROVED'),
  'U1 chip focuses actual Eeschema coordinates, keeps highlighted marker and exposes safe source-linked PCB jump');
 check((await js(`(()=>{const btn=document.querySelector('.sheet-thumb');return btn.getAttribute('aria-current')==='page'&&
  document.getElementById('schematicNext').disabled&&document.getElementById('schematicPrevious').disabled})()`)),
 'single-page project has a faithful one-sheet navigator and disabled impossible next/previous controls');
}
const beforeShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(out+'/native-schematic-gallery-'+kind+'-desktop.png',Buffer.from(beforeShot.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>{const dock=document.getElementById('schematicSheetDock'),
 nav=document.getElementById('schematicPageNav'),foot=document.getElementById('boardFoot'),
 rect=dock.getBoundingClientRect(),f=foot.getBoundingClientRect();
 return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 dock:!dock.hidden,nav:!nav.hidden,buttons:[...dock.querySelectorAll('button')].map(b=>Math.round(b.getBoundingClientRect().width)),
 dockRect:{left:rect.left,right:rect.right,width:rect.width,top:rect.top,bottom:rect.bottom},
 foot:{top:f.top,bottom:f.bottom},mode,source:DATA.source_sha256.slice(0,12)};})()`);
console.log('SCHEMATIC GALLERY MOBILE 390',mobile);
check(mobile.width<=390&&mobile.scroll<=390&&mobile.dock&&mobile.nav&&mobile.buttons.every(x=>x>=40)&&
 mobile.dockRect.left>=0&&mobile.dockRect.right<=390,
 'real native KiCad schematic gallery and stepper remain visible and horizontally safe at 390px');
const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(out+'/native-schematic-gallery-'+kind+'-mobile.png',Buffer.from(shot.data,'base64'));
await call('Emulation.clearDeviceMetricsOverride');
check(errors.length===0,'no actual Chromium JavaScript errors in professional native schematic navigation');
ws.close();console.log('PROFESSIONAL SCHEMATIC GALLERY '+kind.toUpperCase()+' REAL CHROME: ALL PASSED');
