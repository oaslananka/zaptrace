// Real 320-390px Chrome geometry of native KiCad hierarchical schematic.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0),out=process.env.ZAPTRACE_GALLERY_SHOTS;
if(!port||!out)throw Error('Dedicated Chrome debugger and screenshot directory required');
let tab;
for(let attempt=0;attempt<80;attempt++){
 const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 tab=pages.find(p=>p.type==='page'&&p.url.includes('/multi/index.html'));
 if(tab)break;
 await new Promise(resolve=>setTimeout(resolve,100));
}
if(!tab)throw Error('Installed KiCad hierarchical preview missing');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const pending=new Map(),errors=[];
ws.addEventListener('message',ev=>{const v=JSON.parse(ev.data);if(v.method==='Runtime.exceptionThrown')errors.push(v.params.exceptionDetails.text);if(v.id&&pending.has(v.id)){pending.get(v.id)(v);pending.delete(v.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,v=>v.error?reject(Error(JSON.stringify(v.error))):resolve(v.result));ws.send(JSON.stringify({id,method,params}));});
const evaluate=async expr=>{const r=await call('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;};
const ok=(flag,label)=>{if(!flag)throw Error('FAIL '+label);console.log('PASS',label);};
await call('Page.enable');await call('Runtime.enable');
let ready=false;
for(let i=0;i<75;i++){
 try{ready=await evaluate("document.readyState==='complete'&&typeof schematicPageIndex==='number'&&document.getElementById('schematicSheetDock')");if(ready)break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,120));
}
ok(ready,'installed hierarchical KiCad source actually rendered');
await evaluate("document.getElementById('modeSch').click();document.getElementById('schematicNext').click();");
ok(await evaluate("schematicPageIndex===1&&DATA.schematic.pages.length===2"),'actual source child page selected');
const content=await evaluate(`(()=>({
 source:DATA.source_sha256,root:DATA.schematic.pages[0].drawn_element_count,
 child:DATA.schematic.pages[1].drawn_element_count,
 message:document.getElementById('schematicEmptyState').textContent,
 visible:!document.getElementById('schematicEmptyState').hidden,
 dock:document.getElementById('schematicDockScope').textContent,
 sourceReadonly:document.querySelector('header .headside').textContent.includes('NOT FABRICATION APPROVED')}))()`);
console.log('SOURCE_VERIFIED_KICAD_EMPTY_CHILD_STATE',content);
ok(content.root>0&&content.child===0&&content.visible&&content.sourceReadonly&&
 content.message.includes('No drawings on this original KiCad sheet')&&
 content.message.includes('not a rendering failure')&&content.dock.includes('no plotted drawings'),
 'actual native KiCad blank child page has explicit, accurate and accessible source-empty explanation');
const geometryProblems=[];
for(const width of [320,340,360,375,380,390]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
 const result=await evaluate(`(()=>{const $=id=>document.getElementById(id),d=$('schematicSheetDock'),nav=$('schematicPageNav'),f=$('boardFoot');const dock=d.getBoundingClientRect(),foot=f.getBoundingClientRect(),page=nav.getBoundingClientRect();const empty=$('schematicEmptyState').getBoundingClientRect();return {
  emptyVisible:!$('schematicEmptyState').hidden,empty:empty.toJSON(),width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,source:DATA.source_sha256,page:schematicPageIndex,dockHidden:d.hidden,navHidden:nav.hidden,dock:dock.toJSON(),nav:page.toJSON(),foot:foot.toJSON(),buttons:[...d.querySelectorAll('button')].map(x=>x.getBoundingClientRect().width),fab:document.querySelector('header .headside').textContent.includes('NOT FABRICATION APPROVED'),modelHidden:$('render3dControls').hidden};})()`);
 console.log('019_HIERARCHICAL_MOBILE',width,result);
 if(width===320||width===390){const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(`${out}/native-multisheet-child-${width}.png`,Buffer.from(shot.data,'base64'));}
 ok(result.width===width&&result.scroll<=width&&result.source.length===64&&result.page===1&&!result.dockHidden&&!result.navHidden&&result.fab&&result.modelHidden,`real ${width}px KiCad source child sheet / safety status / page overflow`);
 const geometryPass=result.dock.left>=0&&result.dock.right<=width+1&&result.buttons.every(x=>x>=40)&&result.nav.left>=0&&result.nav.right<=width+1&&result.dock.bottom<=result.foot.top+2&&result.emptyVisible&&result.empty.left>=0&&result.empty.right<=width+1&&result.empty.bottom<=result.dock.top+2;
 if(!geometryPass)geometryProblems.push({width,overlapPixels:Math.max(0,result.dock.bottom-result.foot.top)});
 console.log('SCHEMATIC_GEOMETRY',width,geometryPass?'PASS':'DEFECT',Math.max(0,result.dock.bottom-result.foot.top).toFixed(2),'px overlap');
}
ok(geometryProblems.length===0,'no actual 320-390px schematic dock and caution collision: '+JSON.stringify(geometryProblems));
await evaluate("document.getElementById('schematicPrevious').click()");
ok(await evaluate("schematicPageIndex===0&&document.getElementById('schematicEmptyState').hidden&&DATA.schematic.pages[0].drawn_element_count>0"),
 'returning to nonempty original KiCad root sheet removes empty-page explanation');
await evaluate("document.getElementById('modePcb').click()");
ok(await evaluate("document.getElementById('schematicEmptyState').hidden&&document.getElementById('schematicSheetDock').hidden"),
 'source-empty explanation and schematic page controls disappear in PCB mode');
ok(errors.length===0,'no Chrome exceptions during narrow original KiCad child-sheet navigation');
ws.close();console.log('EXACT_019_MULTISHEET_NARROW_CHROME_GEOMETRY=PASS');
