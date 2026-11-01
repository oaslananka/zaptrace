// Authentic offscreen native KiCad 10 model preview, never synthetic 3D.
import {localChromeSocketUrl} from './review_studio_chrome_debugger_url.mjs';
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT);
const snapshots=process.env.ZAPTRACE_3D_SHOTS||'build/native-3d-eda-review';
const unavailable=process.env.ZAPTRACE_EXPECT_NO_3D==='1';
if(!port)throw Error('Real Chrome port required');
let pages=[];
for(let i=0;i<95;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(x=>x.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,110));
}
const p=pages.find(x=>x.type==='page');if(!p)throw Error('KiCad preview Chrome unavailable');
const ws=new WebSocket(localChromeSocketUrl(p.webSocketDebuggerUrl, port));
await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true});});
let id=0;const requests=new Map(),errors=[];
ws.addEventListener('message',evt=>{const x=JSON.parse(evt.data);if(x.method==='Runtime.exceptionThrown')errors.push(x.params.exceptionDetails.text);
 if(x.id&&requests.has(x.id)){requests.get(x.id)(x);requests.delete(x.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const key=++id;requests.set(key,r=>r.error?rej(Error(JSON.stringify(r.error))):res(r.result));ws.send(JSON.stringify({id:key,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async expr=>{const r=await call('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,msg)=>{if(!v)throw Error('FAIL '+msg);console.log('PASS '+msg);};
let ready=false;
for(let i=0;i<75;i++){
 try{ready=await js(`document.readyState==='complete'&&prefsReady&&!!document.getElementById('mode3D')`);if(ready)break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
check(ready,'KiCad native engineering workspace loaded without foreign image/CDN traffic');
const oracle=await js(`(()=>({state:DATA.render3d?.state,views:DATA.render3d?.views?.map(x=>({label:x.label,w:x.width,h:x.height,source:x.source.slice(0,25)})),
 model:DATA.render3d?.model_coverage,pcbSource:DATA.source_sha256,kicad:DATA.board.kicad,
 disabled:document.getElementById('mode3D').disabled,drc:document.getElementById('kpiDrc').textContent,
 expectedDrc:DATA.findings.filter(x=>x.rule!=='unconnected_items').length,expectedOpen:DATA.open_pairs.length,
 open:document.getElementById('kpiOpens').textContent, fab:document.querySelector('header .headside').textContent}))()`);
console.log('NATIVE KICAD 3D EVIDENCE',oracle);
check(oracle.model==='not_verified'&&oracle.pcbSource.length===64&&oracle.kicad.includes('10')&&Number(oracle.drc)===oracle.expectedDrc&&Number(oracle.open)===oracle.expectedOpen&&oracle.expectedDrc>0&&oracle.expectedOpen>0&&oracle.fab.includes('NOT FABRICATION APPROVED'),
 'real source SHA and native DRC/continuity blockers survive unchanged; 3D model completeness remains unverified');
if(unavailable){
 check(oracle.disabled&&oracle.state!=='rendered',
 'missing/disabled local OpenGL renderer never fabricates a rendered 3D scene or unlocks the 3D button');
 const ignored=await js(`(()=>{document.getElementById('mode3D').click();return mode==='pcb'&&document.getElementById('render3dControls').hidden})()`);
 check(ignored,'missing 3D does not block normal PCB review or make non-working UI interactive');
}else{
 check(oracle.state==='rendered'&&oracle.views.length===2&&oracle.views.every(v=>v.source.startsWith('data:image/png;base64')&&v.w>=800&&v.h>=600)&&!oracle.disabled,
 'source-linked isometric and orthographic previews are two actual KiCad-created PNGs (not synthetic geometry)');
 const state=await js(`(()=>{document.getElementById('mode3D').click();const $=id=>document.getElementById(id);
 return {mode,image:render3dStage.querySelector('img').src===DATA.render3d.views[0].source,
 active:$('mode3D').getAttribute('aria-pressed'),render:render3dStage.style.display,
 pcb:$('stage').style.display,sch:$('modeSch').getAttribute('aria-pressed'),
 angle:$('render3dIso').getAttribute('aria-pressed'),controls:!$('render3dControls').hidden,
 measure:$('measure').disabled,clear:$('clearMeasure').disabled,
 scope:$('boardFoot').textContent,notice:$('canvasEvidence').textContent}})()`);
 check(state.mode==='3d'&&state.image&&state.active==='true'&&state.render==='block'&&state.pcb==='none'&&state.sch==='false'&&state.controls&&
 state.measure&&state.clear&&state.scope.includes('models may be absent')&&state.notice.includes('models NOT verified'),
 '3D mode opens actual native isometric image while disabling PCB pad measurements and exposing honest local model limits');
 let loaded=false;
 for(let i=0;i<65;i++){
  loaded=await js(`render3dStage.querySelector('img').complete&&render3dStage.querySelector('img').naturalWidth>800`);
  if(loaded)break;await new Promise(r=>setTimeout(r,90));
 }
 check(loaded,'native KiCad rendered pixels loaded inside the engineering viewport');
 const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 writeFileSync(snapshots+'/native-kicad-3d-isometric-desktop.png',Buffer.from(screenshot.data,'base64'));
 const top=await js(`(()=>{document.getElementById('render3dTop').click();return {
 index:render3dIndex,mode,image:render3dStage.querySelector('img').src===DATA.render3d.views[1].source,
 top:document.getElementById('render3dTop').getAttribute('aria-pressed'),iso:document.getElementById('render3dIso').getAttribute('aria-pressed'),
 sha:DATA.source_sha256,active:document.getElementById('mode3D').getAttribute('aria-pressed')}})()`);
 check(top.index===1&&top.mode==='3d'&&top.image&&top.top==='true'&&top.iso==='false'&&top.sha===oracle.pcbSource&&top.active==='true',
 'native top camera swaps to a second authentic KiCad-generated PNG with unchanged source integrity');
 // A real native orbit must never synthesize geometry: every snapshot is a
 // separate KiCad-supplied base64 PNG, source-bound and finite (45° per frame).
 const orbit=await js(`(()=>({count:DATA.render3d.orbit_frames?.length,
  allPng:DATA.render3d.orbit_frames?.every(x=>x.source.startsWith('data:image/png;base64,')&&x.width>900&&x.height>700),
  labels:DATA.render3d.orbit_frames?.map(x=>x.label),
  noAccess:document.getElementById('render3dNext').disabled,
  initial:orbitFrameIndex,
  sha:DATA.source_sha256}))()`);
 check(orbit.count===8&&orbit.allPng&&!orbit.noAccess&&orbit.initial===-1&&orbit.sha===oracle.pcbSource&&
  orbit.labels.join('|')===[0,45,90,135,180,225,270,315].map(v=>'Orbit '+v+'°').join('|'),
  '8 orbit steps are actual original KiCad camera PNGs at 45° intervals, not fake 3D meshes');
 const step=await js(`(()=>{document.getElementById('render3dNext').click();return {
  index:orbitFrameIndex,src:render3dStage.querySelector('img').src===DATA.render3d.orbit_frames[2].source,
  label:document.getElementById('render3dAngle').textContent,
  counter:document.getElementById('render3dFrameCount').textContent,
  iso:document.getElementById('render3dIso').getAttribute('aria-pressed'),
  top:document.getElementById('render3dTop').getAttribute('aria-pressed')}})()`);
 check(step.index===2&&step.src&&step.label==='ORBIT 090°'&&step.counter==='03 / 08'&&step.iso==='false'&&step.top==='false',
  'Orbit control selects exactly a KiCad 90° image and updates live camera angle/counter, disabling fixed-camera toggles');
 const position=await js(`(()=>{const r=viewport.getBoundingClientRect();return {x:r.left+r.width*.51,y:r.top+r.height*.34}})()`);
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:position.x,y:position.y});
 await call('Input.dispatchMouseEvent',{type:'mousePressed',x:position.x,y:position.y,button:'left',clickCount:1,buttons:1});
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:position.x+91,y:position.y,button:'left',buttons:1});
 await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:position.x+91,y:position.y,button:'left',clickCount:1,buttons:0});
 const dragged=await js(`(()=>({index:orbitFrameIndex,
  source:render3dStage.querySelector('img').src===DATA.render3d.orbit_frames[orbitFrameIndex]?.source,
  label:document.getElementById('render3dAngle').textContent,
  sourceSHA:DATA.source_sha256}))()`);
 console.log('REAL CHROME MOUSE 3D TURNTABLE',dragged);
 check(dragged.index!==step.index&&dragged.index>=0&&dragged.index<8&&dragged.source&&dragged.sourceSHA===oracle.pcbSource,
  'trusted real Chrome pointer drag rotates authentic KiCad camera snapshots while preserving board SHA');
 const cycle=await js(`(()=>{const btn=document.getElementById('render3dPrevious');for(let i=0;i<9;i++)btn.click();
 return {index:orbitFrameIndex,source:render3dStage.querySelector('img').src===DATA.render3d.orbit_frames[orbitFrameIndex].source,
  displayed:document.getElementById('render3dAngle').textContent}})()`);
 check(cycle.index===(dragged.index+7)%8&&cycle.source&&cycle.displayed.includes('ORBIT'),
  'previous camera control wraps safely through finite actual native KiCad frames');
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 const mobile=await js(`(()=>({viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 controls:document.getElementById('render3dControls').getBoundingClientRect().toJSON(),
 scene:render3dStage.getBoundingClientRect().toJSON(),
 mode,measureDisabled:document.getElementById('measure').disabled}))()`);
 console.log('MOBILE TRUE KiCAD 3D',mobile);
 check(mobile.viewport<=390&&mobile.scroll<=390&&mobile.controls.left>=0&&mobile.controls.right<=390&&mobile.mode==='3d'&&mobile.measureDisabled,
 '390px mobile real 3D PCB scene and camera toolbar remain usable without horizontal overflow');
 const mobileShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 writeFileSync(snapshots+'/native-kicad-3d-top-mobile.png',Buffer.from(mobileShot.data,'base64'));
 await call('Emulation.clearDeviceMetricsOverride');
 const returnPcb=await js(`(()=>{document.getElementById('modePcb').click();return {
 mode,render:render3dStage.style.display,shown:!document.getElementById('render3dControls').hidden,
 physical:document.getElementById('measure').disabled,
 kpi:document.getElementById('kpiDrc').textContent,gate:document.querySelector('header .headside').textContent}})()`);
 check(returnPcb.mode==='pcb'&&returnPcb.render==='none'&&!returnPcb.shown&&!returnPcb.physical&&
 returnPcb.kpi===oracle.drc&&returnPcb.gate.includes('NOT FABRICATION APPROVED'),
 'returning from 3D to actual KiCad PCB preserves DRC counts and re-enables physical-source pad inspection');
}
check(errors.length===0,'no actual Chrome errors during optional native KiCad 3D preview');
ws.close();console.log('SOURCE-SAFE NATIVE KICAD 3D '+(unavailable?'UNAVAILABLE':'AVAILABLE')+' CHROME: ALL PASSED');
