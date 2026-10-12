import {writeFileSync,mkdirSync} from 'node:fs';
const port=Number(process.env.CDP_PORT);
const screenshotDir=process.env.ZAPTRACE_MOBILE_3D_QA_DIR||'build/qa-021-mobile3d';
mkdirSync(screenshotDir,{recursive:true});
if(!port)throw Error('CDP port unavailable');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let pages;
for(let i=0;i<90;i++){try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.length)break;}catch{} await wait(100);}
const page=pages?.find(p=>p.url?.endsWith('/index.html'));
if(!page)throw Error('Owned native KiCad source page unavailable');
const socket=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((a,b)=>{socket.addEventListener('open',a,{once:true});socket.addEventListener('error',b,{once:true});});
let id=0;const pending=new Map(),faults=[];
socket.addEventListener('message',ev=>{const msg=JSON.parse(ev.data);if(msg.method==='Runtime.exceptionThrown')faults.push(msg.params.exceptionDetails.text);if(msg.id&&pending.has(msg.id)){pending.get(msg.id)(msg);pending.delete(msg.id);}});
function call(method,params={}){return new Promise((ok,no)=>{const n=++id;pending.set(n,m=>m.error?no(Error(JSON.stringify(m.error))):ok(m.result));socket.send(JSON.stringify({id:n,method,params}));});}
async function js(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
function check(bool,msg,data){if(!bool)throw Error('MOBILE_021_CAMERA_LAYOUT_FAIL '+msg+' :: '+JSON.stringify(data));console.log('MOBILE_021_CAMERA_PASS',msg);}
await call('Runtime.enable');await call('Page.enable');
for(let i=0;i<100;i++){if(await js("document.readyState==='complete' && typeof DATA==='object'"))break;await wait(100);}
check(await js("DATA.source_sha256==='fb3a0acbcafcdfe260a11eb6db216701c1b5ebf4eb57af4a6e46ce1e6b1eb2ce'"),'exact original native KiCad source digest not changed');
for(const width of [320,390,1440]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,mobile:width<750,deviceScaleFactor:1});
 await js("document.getElementById('mode3D').click();document.getElementById('render3dNext').click()");
 await wait(100);
 const result=await js(`(()=>{const ids=['render3dIso','render3dTop','render3dPrevious','render3dNext'];const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};const angle=document.querySelector('.render3d-angle');const ar=angle.getBoundingClientRect();const nav=document.querySelector('.boardactions').getBoundingClientRect();const panel=document.getElementById('render3dControls').getBoundingClientRect();return {width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,actions:Object.fromEntries(ids.map(id=>[id,rect(id)])),angle:{x:ar.x,y:ar.y,w:ar.width,h:ar.height,text:angle.innerText,scrollWidth:angle.scrollWidth,clientWidth:angle.clientWidth},panel:{top:panel.top,bottom:panel.bottom},toolbar:{top:nav.top,bottom:nav.bottom},visible:!document.getElementById('render3dControls').hidden,frames:DATA.render3d?.orbit_frames?.length}})()`);
 console.log('MOBILE_021_CAMERA_GEOMETRY',width,JSON.stringify(result));
 check(result.visible&&result.frames===8&&result.scroll<=width+1,`${width}px source-native KiCad camera, no page overflow`,result);
 if(width<=420){
  const {render3dIso:iso,render3dTop:top,render3dPrevious:prev,render3dNext:next}=result.actions;
  check(Math.abs(iso.y-top.y)<2&&Math.abs(prev.y-next.y)<2&&prev.y>iso.bottom-3,`${width}px two deliberate camera control rows`,result);
  check(iso.w>=80&&top.w>=80&&prev.w>=44&&next.w>=44&&[iso,top,prev,next].every(x=>x.h>=43),`${width}px legible minimum target heights and widths`,result);
  check(result.angle.w>=88&&result.angle.clientWidth>=result.angle.scrollWidth&&result.angle.text.includes('ORBIT'),`${width}px full native orbit angle visible`,result);
  check(result.toolbar.bottom+4<=result.panel.top,`${width}px control panel does not overlap primary PCB toolbar`,result);
 }
 const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 writeFileSync(`${screenshotDir}/mobile-camera-${width}.png`,Buffer.from(shot.data,'base64'));
}
check(faults.length===0,'zero real Chrome JS exceptions',faults);
socket.close();console.log('MOBILE_021_REAL_SOURCE_BOUND_CHROME_CAMERA_QA=PASS');
