import {localChromeSocketUrl} from './review_studio_chrome_debugger_url.mjs';
import {writeFileSync} from 'node:fs';
const cdp=Number(process.env.CDP_PORT),host=Number(process.env.HTTP_PORT);
const shots=process.env.ZAPTRACE_027_SCREEN_DIR||'build/qa-027-visual';
if(!cdp||!host)throw Error('Owned local Chrome/debug port missing');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let pages=[];
for(let i=0;i<130;i++) {try{pages=await(await fetch(`http://127.0.0.1:${cdp}/json/list`)).json();if(pages.length)break;}catch{}await sleep(100)}
const page=pages.find(p=>p.url?.includes('index.html'));
if(!page)throw Error('No native source-backed KiCad 3D browser tab');
const ws=new WebSocket(localChromeSocketUrl(page.webSocketDebuggerUrl, cdp));
await new Promise((ok,no)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',no,{once:true})});
let id=0;const pending=new Map(),faults=[];
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')faults.push(m.params.exceptionDetails.text);if(pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id)}});
const call=(method,params={})=>new Promise((ok,no)=>{const n=++id;pending.set(n,m=>m.error?no(Error(JSON.stringify(m.error))):ok(m.result));ws.send(JSON.stringify({id:n,method,params}))});
const js=async expression=>{const res=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(res.exceptionDetails)throw Error(JSON.stringify(res.exceptionDetails));return res.result.value};
function ok(test,name,detail){if(!test)throw Error(`027_REAL_CHROME_VISUAL_FAIL ${name} ${JSON.stringify(detail)}`);console.log('027_REAL_CHROME_VISUAL_PASS',name)}
await call('Runtime.enable');await call('Page.enable');
for(let i=0;i<120;i++){if(await js("document.readyState==='complete'&&typeof DATA==='object'"))break;await sleep(80)}
ok(await js("DATA.source_sha256==='fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce' && DATA.render3d?.state==='rendered'"),'original KiCad OpenGL source and 3D untouched');
await js("switchMode('3d');document.getElementById('render3dModelDiagnostics').open=true");
for(const width of [320,381,390,1440]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,mobile:width<751,deviceScaleFactor:1});
 await sleep(100);await js('fit()');await sleep(50);
 const g=await js(`(()=>{const r=render3dStage.getBoundingClientRect(),p=document.getElementById('render3dControls').getBoundingClientRect(),tools=document.querySelector('.boardactions').getBoundingClientRect();const intersect=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,model:r.toJSON(),panel:p.toJSON(),overlap:intersect(r,p),toolbarOverlap:intersect(tools,p),modelVisible:r.height>100&&r.width>145,diagnostics:document.getElementById('render3dModelDiagnostics').open,cover:DATA.board.model_assets.model_geometry_approved,orbit:DATA.render3d.orbit_frames.length,stage:document.querySelector('#render3dControls')?.hidden}})()`);
 console.log('027_REAL_3D_GEOMETRY',width,JSON.stringify(g));
 ok(g.width>=width-20&&g.scroll===g.width&&g.modelVisible&&g.overlap<=1&&g.toolbarOverlap<=1&&g.diagnostics&&g.cover===false&&g.orbit===8,`${width}px real KiCad 3D model and model warning cannot overlap; full orbit available`,g);
 const snap=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(`${shots}/3d-${width}.png`,Buffer.from(snap.data,'base64'));
}
await call('Page.navigate',{url:`http://127.0.0.1:${host}/multi.html`});
for(let i=0;i<120;i++){if(await js("document.readyState==='complete'&&typeof DATA==='object' && DATA.erc?.count===28"))break;await sleep(80)}
for(const width of [320,390,1440]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,mobile:width<751,deviceScaleFactor:1});
 const g=await js(`(()=>({source:DATA.source_sha256,erc:DATA.erc,section:document.getElementById('ercBadge').textContent,badgeClass:document.getElementById('ercBadge').className,kpiClass:document.getElementById('kpiErc').className,note:document.getElementById('kpiErcNote').textContent,width:document.documentElement.clientWidth,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth}))()`);
 console.log('027_REAL_KICAD_WARNING_SEVERITY',width,JSON.stringify(g));
 ok(g.source==='fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce'&&g.erc.errors===0&&g.erc.warnings===28&&g.badgeClass==='warn'&&g.kpiClass.includes('caution')&&g.note.includes('0 errors')&&g.note.includes('28 warnings')&&g.overflow<=0,`${width}px 28 KiCad warnings stay warnings (amber), never critical-red`,g);
 const snap=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(`${shots}/erc-${width}.png`,Buffer.from(snap.data,'base64'));
}
const original=await js("({...DATA.erc})");
const critical=await js("DATA.erc.errors=1;DATA.erc.warnings=27;summary();({className:document.getElementById('kpiErc').className,badge:document.getElementById('ercBadge').className})");
ok(critical.className.includes('danger')&&critical.badge==='critical','negative fixture with one ERC error remains critical-red',critical);
const unrun=await js("DATA.erc.state='not_run';summary();({value:document.getElementById('kpiErc').textContent,badge:document.getElementById('ercBadge').textContent,className:document.getElementById('kpiErc').className})");
ok(unrun.value==='—'&&unrun.badge==='Not checked'&&!unrun.className.includes('okay'),'not-run ERC remains unknown, never falsely green',unrun);
await js(`Object.assign(DATA.erc,${JSON.stringify(original)});summary()`);
ok(faults.length===0,'zero browser JS exceptions across source 3D and Eeschema',faults);
ws.close();console.log('EXACT_027_SOURCE_KICAD_UNOCCLUDED_3D_AND_ERC_SEVERITY_ALL_VIEWPORTS=PASS');
