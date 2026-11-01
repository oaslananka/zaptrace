// Isolated Chrome profile: verify source-keyed layout persistence over a real reload.
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9795);
let pages;
for(let i=0;i<60;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}
 catch{}await new Promise(r=>setTimeout(r,125));
}
const page=pages?.find(x=>x.type==='page');if(!page)throw Error('Review Studio Chrome page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const pending=new Map();
ws.addEventListener('message',event=>{const data=JSON.parse(event.data);if(data.id&&pending.has(data.id)){pending.get(data.id)(data);pending.delete(data.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const id=++seq;pending.set(id,data=>data.error?rej(Error(JSON.stringify(data.error))):res(data.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('Page.enable');
async function js(src){const data=await call('Runtime.evaluate',{expression:src,returnByValue:true,awaitPromise:true});if(data.exceptionDetails)throw Error(JSON.stringify(data.exceptionDetails));return data.result.value;}
function check(condition,message){if(!condition)throw Error(message);console.log('PASS',message);}
let initial=await js(`(()=>({source:DATA.source_sha256,storage:typeof localStorage!=='undefined',state:document.getElementById('prefsStatus').textContent}))()`);
console.log('LOCAL LAYOUT',initial);
check(initial.storage,'local browser supports private profile-local layout storage');
const chosen=await js(`(()=>{const $=id=>document.getElementById(id);
 setTab('pins');switchMode('schematic');
 for(const [id,on] of [['showPadMarkers',false],['showFaultMarkers',false]]){
  $(id).checked=on;$(id).dispatchEvent(new Event('change'));
 }
 const layer=$('layerPicker').querySelectorAll('input')[0];layer.checked=false;
 layer.dispatchEvent(new Event('change'));
 const dock=$('rightSplitter');dock.focus();
 dock.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
 const value=JSON.parse(localStorage.getItem(PREF_KEY));
 return {value,sha:DATA.source_sha256,dockWidth:document.getElementById('rightSidebar').getBoundingClientRect().width};})()`);
check(chosen.value.version===1&&chosen.value.tab==='pins'&&chosen.value.mode==='schematic'&&
 chosen.value.markers.showPadMarkers===false&&chosen.value.markers.showFaultMarkers===false&&
 chosen.value.panels.right>346&&chosen.value.layers['F.Cu']===false,
 'native local layout is saved with a per-source SHA key, including tab, layers and panel widths');
await call('Page.reload',{ignoreCache:true});
let loaded=null;
for(let i=0;i<50;i++){
 try{loaded=await js(`(()=>({ok:document.readyState==='complete'&&typeof prefsReady==='boolean'&&prefsReady,
 mode:typeof mode==='undefined'?null:mode,tab:typeof tab==='undefined'?null:tab,
 visible:typeof visible==='undefined'?null:visible['F.Cu'],
 pads:document.getElementById('showPadMarkers')?.checked,
 faults:document.getElementById('showFaultMarkers')?.checked,
 dock:document.getElementById('rightSidebar')?.getBoundingClientRect().width,
 status:document.getElementById('prefsStatus')?.textContent}))()`);if(loaded?.ok)break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,150));
}
console.log('LOCAL LAYOUT RESTORED',loaded);
check(loaded?.ok&&loaded.mode==='schematic'&&loaded.tab==='pins'&&loaded.visible===false&&
 loaded.pads===false&&loaded.faults===false&&loaded.dock>346&&loaded.status.includes('Restored'),
 'real Chrome page reload restores exactly same PCB-scope layout, not source data or fab status');
const reset=await js(`(()=>{document.getElementById('resetPreferences').click();
 return {key:localStorage.getItem(PREF_KEY),tab,mode,layer:visible['F.Cu'],
 pads:document.getElementById('showPadMarkers').checked,
 dock:document.querySelector('.app').style.getPropertyValue('--right-width'),
 summary:document.getElementById('kpiDrc').textContent};})()`);
check(reset.key===null&&reset.tab==='issues'&&reset.mode==='pcb'&&reset.layer===true&&
 reset.pads===true&&reset.dock===''&&reset.summary==='16',
 'Reset layout clears source-scoped browser prefs and restores native check results without alteration');
const hostile=await js(`(()=>{localStorage.setItem(PREF_KEY,'{"version":1,"tab":"faked_fab_approved","mode":"schematic","layers":{"F.Cu":"yes"},"panels":{"right":50000}}');
 return true;})()`);
await call('Page.reload',{ignoreCache:true});
let malicious=null;
for(let i=0;i<50;i++){
 try{malicious=await js(`(()=>({ok:document.readyState==='complete'&&prefsReady,tab,mode,
 layer:visible['F.Cu'],right:document.getElementById('rightSidebar').getBoundingClientRect().width,
 drc:document.getElementById('kpiDrc').textContent,
 fab:document.querySelector('.headside')?.textContent}))()`);if(malicious.ok)break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,120));
}
check(malicious?.ok&&malicious.tab==='issues'&&malicious.layer===true&&malicious.right<600&&
 malicious.drc==='16'&&malicious.fab.includes('NOT FABRICATION APPROVED'),
 'invalid or malicious stored values cannot invent a review tab, clear DRC or change fabrication gate');
await js(`(()=>{localStorage.removeItem(PREF_KEY)})()`);
ws.close();console.log('SOURCE-SCOPED REAL CHROME PREFERENCES: ALL PASSED');
