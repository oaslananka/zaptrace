// Exact installed-package real-Chrome mechanical file diagnostics (not certification).
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
const shot=process.env.ZAPTRACE_019_SCREENSHOT;
if(!port||!shot)throw Error('Chrome CDP and disposable QA screenshot required');
const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page=pages.find(p=>p.type==='page'&&p.url?.includes('/three-d/index.html'));
if(!page)throw Error('Real KiCad 3D screen not available');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let id=0;const pending=new Map();const errors=[];
ws.addEventListener('message',ev=>{const data=JSON.parse(ev.data);
 if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails.text);
 if(data.id&&pending.has(data.id)){pending.get(data.id)(data);pending.delete(data.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const value=++id;
 pending.set(value,data=>data.error?reject(Error(JSON.stringify(data.error))):resolve(data.result));
 ws.send(JSON.stringify({id:value,method,params}));});
const evalJs=async source=>{const result=await call('Runtime.evaluate',{expression:source,returnByValue:true,awaitPromise:true});
 if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value;};
const pass=(ok,text)=>{if(!ok)throw Error('FAIL '+text);console.log('PASS',text);};
await call('Page.enable');await call('Runtime.enable');await call('Page.bringToFront');
for(let i=0;i<80;i++){
 if(await evalJs("document.readyState==='complete'&&typeof DATA==='object'&&document.getElementById('render3dModelDiagnostics')"))break;
 await new Promise(r=>setTimeout(r,120));
}
const focusDiagnostic=await evalJs(`(()=>{document.getElementById('mode3D').click();
 const panel=document.getElementById('render3dModelDiagnostics');panel.open=false;
 const summary=panel.querySelector('summary');summary.focus();
 const box=summary.getBoundingClientRect();return {focused:document.activeElement===summary,
 mode3D:document.getElementById('render3dControls').hidden,
 computed:getComputedStyle(summary).display,html:summary.outerHTML.slice(0,190),rect:box.toJSON()};})()`);
console.log('NATIVE_DISCLOSURE_FOCUS',focusDiagnostic);
pass(focusDiagnostic.focused&&!focusDiagnostic.mode3D&&focusDiagnostic.rect.width>180,
 'native summary element is visible, focused and keyboard addressable in 3D mode');
await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
let keyboardOpen=await evalJs("document.getElementById('render3dModelDiagnostics').open");
console.log('CDP_ENTER_DETAILS_OPEN',keyboardOpen);
if(!keyboardOpen){
 await call('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32});
 await call('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
 keyboardOpen=await evalJs("document.getElementById('render3dModelDiagnostics').open");
 console.log('CDP_SPACE_DETAILS_OPEN',keyboardOpen);
}
pass(keyboardOpen,'real Chrome keyboard opens 3D model file diagnostics using accessible disclosure control');
const diag=await evalJs(`(()=>{const d=DATA.board.model_assets;
 const more=document.getElementById('render3dModelDiagnostics');
 return {source:DATA.source_sha256,kicad:DATA.board.kicad,fp:d.footprints,total:d.declared_references,
 present:d.present_files,unresolved:d.unresolved_refs,unmodelled:d.without_model_refs,
 substitutes:d.same_stem_step_candidates,approved:d.model_geometry_approved,
 summary:document.getElementById('render3dModelSummary').textContent,
 detail:document.getElementById('render3dModelDetails').textContent,
 open:more.open,mode:document.getElementById('mode3D').getAttribute('aria-pressed'),
 fab:document.querySelector('header .headside').textContent}})()`);
console.log('REAL_SOURCE_3D_DIAGNOSTICS',diag);
pass(diag.fp===14&&diag.total===12&&diag.present===10&&diag.approved===false&&
 diag.unresolved.join(',')==='J1,U1'&&diag.unmodelled.join(',')==='TP1,TP2'&&
 diag.substitutes.join(',')==='J1,U1'&&diag.open&&diag.mode==='true',
 'installed KiCad 10 screenshot shows exact 14 footprints, 12 links, 10 files, 4 blocked source objects');
pass(diag.detail.includes('J1, U1')&&diag.detail.includes('TP1, TP2')&&
 diag.detail.includes('STEP candidates (NOT verified)')&&diag.detail.includes('NOT verified')&&
 diag.summary.includes('10/12')&&diag.fab.includes('NOT FABRICATION APPROVED')&&diag.source.length===64,
 '3D model omissions and mechanical approval remain visible and source-SHA linked');
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await evalJs(`(()=>{const audit=document.getElementById('render3dModelDiagnostics');
 audit.scrollIntoView({block:'center'});const r=audit.getBoundingClientRect();
 return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 panelWidth:r.width,panelLeft:r.left,panelRight:r.right,
 headline:document.getElementById('render3dModelSummary').getBoundingClientRect().width,
 warningWidth:document.querySelector('.render3d-warning').getBoundingClientRect().width,
 warningHeight:document.querySelector('.render3d-warning').getBoundingClientRect().height,
 actionGridWidth:document.querySelector('.render3d-actions').getBoundingClientRect().width,
 disclosure:getComputedStyle(document.querySelector('.render3d-warning')).display,
 open:audit.open}})()`);
console.log('390PX_REAL_3D_DIAGNOSTICS',mobile);
pass(mobile.width<=390&&mobile.scroll<=mobile.width&&mobile.panelWidth>190&&
 mobile.panelLeft>=0&&mobile.panelRight<=mobile.width+2&&mobile.headline>150&&mobile.open&&
 mobile.disclosure!=='none'&&mobile.warningWidth>=mobile.actionGridWidth*.88&&mobile.warningHeight<85,'390px model card has full-row readable warning and no horizontal overflow');
const result=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shot,Buffer.from(result.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:320,height:780,deviceScaleFactor:1,mobile:true});
const narrow=await evalJs(`(()=>{const p=document.querySelector('.render3d-diagnostics');
 p.scrollIntoView({block:'center'});
 const n=p.getBoundingClientRect(), warning=document.querySelector('.render3d-warning').getBoundingClientRect(),
 actions=document.querySelector('.render3d-actions').getBoundingClientRect();
 return {client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 panel:n.toJSON(),warning:warning.toJSON(),actions:actions.toJSON(),open:p.open,
 toolbar:document.querySelector('.boardactions').getBoundingClientRect().toJSON(),
 controls:document.querySelector('.render3d-controls').getBoundingClientRect().toJSON(),
 scene:document.querySelector('.boardspace').getBoundingClientRect().toJSON()}})()`);
console.log('320PX_REAL_3D_DIAGNOSTICS',narrow);
const toolbarOverlap=Math.max(0,Math.min(narrow.toolbar.bottom,narrow.controls.bottom)-Math.max(narrow.toolbar.top,narrow.controls.top));
console.log('320PX_3D_CONTROL_TOOLBAR_VERTICAL_OVERLAP_PX',toolbarOverlap);
pass(toolbarOverlap<=1,'320px real native 3D model disclosure does not cover the PCB mode and tool controls');
pass(narrow.client===320&&narrow.scroll<=320&&narrow.panel.width>240&&
 narrow.panel.left>=0&&narrow.panel.right<=321&&narrow.warning.width>=narrow.actions.width*.85&&
 narrow.warning.height<95&&narrow.open,'320px narrow-phone model panel and safety disclaimer remain readable with no horizontal scroll');
const narrowShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shot.replace('-390.png','-320.png'),Buffer.from(narrowShot.data,'base64'));
for(const width of [340,360,375,380,381,385,390]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
 const box=await evalJs(`(()=>{const tools=document.querySelector('.boardactions').getBoundingClientRect();
  const popup=document.querySelector('.render3d-controls').getBoundingClientRect();
  return {viewport:document.documentElement.clientWidth,
   overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
   overlap:Math.max(0,Math.min(tools.bottom,popup.bottom)-Math.max(tools.top,popup.top)),
   popupLeft:popup.left,popupRight:popup.right}})()`);
 console.log('RESPONSIVE_NATIVE_3D',width,box);
 pass(box.viewport===width&&box.overflow<=0&&box.overlap<=1&&box.popupLeft>=0&&box.popupRight<=width+1,
  `real ${width}px Chrome 3D controls do not occlude navigation or exceed viewport`);
}
const scope=await evalJs(`(()=>{document.getElementById('modePcb').click();
 const panel=document.getElementById('render3dModelDiagnostics');
 const root=document.getElementById('render3dControls');
 const hidden=root.hidden&&root.contains(panel)&&!panel.getBoundingClientRect().width;
 document.getElementById('mode3D').click();return {hidden,restored:!root.hidden&&root.contains(panel),
 state:document.getElementById('mode3D').getAttribute('aria-pressed'),
 fab:document.querySelector('header .headside').textContent}})()`);
pass(scope.hidden&&scope.restored&&scope.state==='true'&&scope.fab.includes('NOT FABRICATION APPROVED'),
 '3D model disclosure is hidden in PCB mode, restored only in real KiCad 3D mode without changing safety status');
pass(errors.length===0,'no native Chromium exceptions while opening source model diagnostics');
ws.close();console.log('EXACT_019_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS');
