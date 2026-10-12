// Real Chrome workspace keyboard, accessibility and small-viewport regression.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||0);
if(!port)throw Error('Real Chrome CDP port required');
let tabs=[];
for(let i=0;i<90;i++){
 try{tabs=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();if(tabs.some(t=>t.type==='page'))break;}catch{}
 await new Promise(resolve=>setTimeout(resolve,120));
}
const auditUrl=process.env.ZAPTRACE_AUDIT_URL;
const tab=auditUrl?tabs.find(t=>t.type==='page'&&t.url===auditUrl):
 tabs.find(t=>t.type==='page'&&t.url?.startsWith('http://127.0.0.1:'))||tabs.find(t=>t.type==='page');
console.log('CHROME TAB',tab?.url);
if(!tab)throw Error('No Chrome workspace tab');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{
 ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});
});
let id=0;const callbacks=new Map(),errors=[];
ws.addEventListener('message',event=>{
 const r=JSON.parse(event.data);
 if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);
 if(r.id&&callbacks.has(r.id)){callbacks.get(r.id)(r);callbacks.delete(r.id);}
});
const cmd=(method,params={})=>new Promise((resolve,reject)=>{
 const value=++id;callbacks.set(value,r=>r.error?reject(Error(JSON.stringify(r.error))):resolve(r.result));
 ws.send(JSON.stringify({id:value,method,params}));
});
const evaluate=async expression=>{
 const r=await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
 if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
 return r.result.value;
};
const pass=(valid,label)=>{if(!valid)throw Error('FAIL '+label);console.log('PASS',label);};
await cmd('Runtime.enable');await cmd('Page.enable');await cmd('DOM.enable');
for(let i=0;i<70;i++){
 const ready=await evaluate("document.readyState==='complete' && !!document.getElementById('runtimeMode')");
 if(ready)break;
 if(i===69)throw Error('Review Studio page not loaded '+await evaluate('location.href'));
 await new Promise(resolve=>setTimeout(resolve,130));
}
const loaded=await evaluate("(()=>({mode:document.getElementById('runtimeMode')?.textContent,skip:document.querySelector('.skip-to-content')?.getAttribute('href'),main:document.querySelector('main')?.id,info:document.getElementById('projectSearchFeedback')?.textContent,version:document.querySelector('.foot')?.textContent,status:document.querySelector('.gate')?.textContent,count:document.querySelectorAll('.project').length}))()");
console.log('WORKSPACE A11Y',loaded);
pass(loaded.mode==='LOCAL · GUARDED ECO'&&loaded.skip==='#workspaceMain'&&loaded.main==='workspaceMain'&&loaded.version.includes(process.env.ZAPTRACE_EXPECT_VERSION||'0.1.12')&&loaded.status.includes('NOT FABRICATION APPROVED'),'truthful runtime, version, landmark and fab boundary');
pass(loaded.info===loaded.count+' native snapshots available','project count accessible at first load');
const nameless=await evaluate("(()=>{const items=[...document.querySelectorAll('a,button,input,select,textarea')];return items.filter(el=>{if(el.closest('[hidden]')||getComputedStyle(el).display==='none')return false;if(el.type==='hidden')return false;const name=el.getAttribute('aria-label')||el.getAttribute('aria-labelledby')||el.labels?.[0]?.textContent||el.textContent||el.getAttribute('title');return !name?.trim();}).map(el=>el.outerHTML.slice(0,160));})()");
pass(nameless.length===0,'all visible workspace links, buttons and form inputs expose an accessible name: '+nameless.join(' | '));

if(process.env.ZAPTRACE_EXPECT_TWO){
 pass(loaded.count===2,'two source-linked real KiCad review cards are present');
 const match=await evaluate("(()=>{const search=document.getElementById('filterProjects');search.value='copper';search.dispatchEvent(new Event('input',{bubbles:true}));const count=[...document.querySelectorAll('.project')].filter(x=>!x.hidden).length;const result=document.getElementById('projectSearchFeedback').textContent;search.value='';search.dispatchEvent(new Event('input',{bubbles:true}));return {count,result};})()");
 pass(match.count===1&&match.result==='Showing 1 of 2 native snapshots','real project search filters by source name');
 const comparison=await evaluate("(()=>{const checks=[...document.querySelectorAll('.compare-checkbox')];if(checks.length!==2)return {count:checks.length};checks.forEach(node=>{node.checked=true;node.dispatchEvent(new Event('change',{bubbles:true}));});const panel=document.getElementById('comparePanel');const shown=!panel.hidden;const guard=panel.textContent.includes('NOT')||panel.textContent.includes('not');document.getElementById('compareClear').click();return {count:checks.length,shown,guard,cleared:panel.hidden,unselected:checks.every(x=>!x.checked)};})()");
 pass(comparison.count===2&&comparison.shown&&comparison.guard&&comparison.cleared&&comparison.unselected,
  'two real snapshots compare without implying rule equivalence; clear returns selection to zero');
}

await evaluate("document.querySelector('.skip-to-content').focus();true");
await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'/',code:'Slash',windowsVirtualKeyCode:191});
await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'/',code:'Slash',windowsVirtualKeyCode:191});
pass(await evaluate("document.activeElement.id==='filterProjects'"),'slash focuses project search');
let result=await evaluate("(()=>{const search=document.getElementById('filterProjects');search.value='no-match-qa';search.dispatchEvent(new Event('input',{bubbles:true}));return {feedback:document.getElementById('projectSearchFeedback').textContent,empty:!document.getElementById('emptyFilter').hidden,visible:[...document.querySelectorAll('.project')].filter(x=>!x.hidden).length};})()");
pass(result.feedback==='Showing 0 of '+loaded.count+' native snapshots'&&result.empty&&result.visible===0,'empty result announced');
await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
result=await evaluate("(()=>({text:document.getElementById('filterProjects').value,empty:document.getElementById('emptyFilter').hidden,feedback:document.getElementById('projectSearchFeedback').textContent,shown:[...document.querySelectorAll('.project')].filter(x=>!x.hidden).length}))()");
pass(result.text===''&&result.empty&&result.shown===loaded.count&&result.feedback===loaded.count+' native snapshots available','Escape restores search and project cards');
const typing=await evaluate("(()=>{const input=document.getElementById('ecoRef');input.focus();input.value='R1';document.dispatchEvent(new KeyboardEvent('keydown',{key:'/',bubbles:true,cancelable:true}));return {active:document.activeElement.id,value:input.value};})()");
pass(typing.active==='ecoRef'&&typing.value==='R1','shortcut never steals input focus');
const rejected=await evaluate(`(async()=>{
 const fields=[['ecoForm','ecoStatus'],['pcbEcoForm','pcbEcoStatus'],
  ['copperInspectForm','copperStatus'],['pcbAuditForm','pcbAuditStatus'],
  ['nativeRestoreForm','nativeRestoreStatus'],['nativeImportForm','nativeJob']];
 const issues=[];
 for(const [formId,statusId] of fields){
  const form=document.getElementById(formId);form.reset();
  form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
  await new Promise(resolve=>setTimeout(resolve,85));
  const el=document.getElementById(statusId);
  issues.push({formId,statusId,role:el.getAttribute('role'),
   live:el.getAttribute('aria-live'),error:el.classList.contains('error'),
   visible:!el.hidden,message:el.textContent});
 }
 return issues;
})()`);
console.log('INVALID NATIVE ENGINEERING FORMS',rejected);
pass(rejected.length===6&&rejected.every(x=>x.visible&&x.error&&
 x.role==='alert'&&x.live==='assertive'&&x.message.length>20),
 'all six live native engineering forms announce actionable invalid-input errors without running KiCad');

const focus=await evaluate("(()=>{const node=document.querySelector('.skip-to-content');node.focus();return {visible:getComputedStyle(node).transform,focused:document.activeElement===node};})()");
pass(focus.focused&&focus.visible==='none','skip link visible when keyboard focused');
await evaluate("document.activeElement.blur()");
if(process.env.ZAPTRACE_EXPECT_TWO){
 let imagesReady=false;
 for(let i=0;i<70;i++){
  imagesReady=await evaluate("[...document.querySelectorAll('.project .art img')].some(img=>img.complete&&img.naturalWidth>0)");
  if(imagesReady)break;
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 pass(imagesReady,'registered source review thumbnails actually load in Chrome');
}

for(const width of [1440,768,390,320]){
 await cmd('Emulation.setDeviceMetricsOverride',{width,height:850,deviceScaleFactor:1,mobile:width<769});
 const metrics=await evaluate("(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,search:document.getElementById('filterProjects').getBoundingClientRect().toJSON(),feedback:document.getElementById('projectSearchFeedback').getBoundingClientRect().toJSON(),mode:getComputedStyle(document.getElementById('runtimeMode')).display}))()");
 console.log('VIEWPORT',width,{width:metrics.width,scroll:metrics.scroll,search:metrics.search.width});
 pass(metrics.width<=width&&metrics.scroll<=width&&metrics.search.right<=width&&metrics.search.width>=Math.min(250,width-35)&&metrics.feedback.right<=width&&(width>390||metrics.mode!=='none'),'viewport '+width+'px avoids horizontal overflow');
 if(process.env.ZAPTRACE_UX_SCREENSHOTS&&(width===1440||width===390)){
  const shot=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  writeFileSync(process.env.ZAPTRACE_UX_SCREENSHOTS+'/workspace-'+width+'.png',Buffer.from(shot.data,'base64'));
 }

}
if(process.env.ZAPTRACE_EXPECT_TWO){
 await cmd('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 const url=await evaluate("document.querySelector('.project .actions a.primary')?.href");
 pass(typeof url==='string'&&url.includes('/review-assets/'),'registered native reviewer uses safe opaque localhost link');
 await cmd('Page.navigate',{url});
 let opened=null;
 for(let i=0;i<90;i++){
  opened=await evaluate("(()=>({url:location.href,ready:document.readyState,title:document.title,body:document.body?.textContent?.slice(0,5000)||''}))()");
  if(opened.ready==='complete'&&opened.url===url&&opened.body.length>200)break;
  await new Promise(resolve=>setTimeout(resolve,110));
 }
 pass(opened?.url===url&&opened.ready==='complete'&&opened.body.length>200&&
  /KiCad|Review Studio|PCB/.test(opened.title+opened.body),
  'registered independent native KiCad reviewer actually opens via verified localhost asset endpoint');
 const sandbox=await evaluate("(async()=>{let rootReadable=false;try{const r=await fetch('/');rootReadable=r.ok;}catch{}return {origin:self.origin,rootReadable};})()");
 pass(sandbox.origin==='null'&&!sandbox.rootReadable,
  'registered native HTML runs under opaque CSP sandbox, cannot fetch privileged localhost workspace');
 let hydrated={};
 for(let i=0;i<80;i++){
  hydrated=await evaluate("(()=>({name:document.getElementById('boardName')?.textContent,meta:document.getElementById('boardMeta')?.textContent,canvas:document.getElementById('canvasName')?.textContent,layers:document.querySelectorAll('#layerPicker input').length,pads:document.querySelectorAll('.pad-hit').length,images:[...document.images].filter(x=>x.complete&&x.naturalWidth>0).length}))()");
  if(hydrated.name&&hydrated.layers>0&&hydrated.pads>0&&hydrated.images>0)break;
  await new Promise(resolve=>setTimeout(resolve,110));
 }
 console.log('REGISTERED NATIVE REVIEWER HYDRATION',hydrated);
 pass(hydrated.name?.includes('ESP32')&&hydrated.meta?.includes('actual KiCad')&&hydrated.layers>0&&hydrated.pads>0&&hydrated.images>0,
  'sandboxed actual native PCB viewer hydrates KiCad pad geometry, copper layer controls and native plots');
 const nativeInspector=await evaluate("(()=>{const pad=document.querySelector('.pad-hit');const sourceLabel=pad?.getAttribute('aria-label')||'';pad?.click();const detail=document.getElementById('detail')?.textContent||'';return {sourceLabel,detail,selected:pad?.classList.contains('selected')};})()");
 pass(nativeInspector.sourceLabel.includes('Inspect pad')&&nativeInspector.selected&&nativeInspector.detail.includes('Pad size')&&nativeInspector.detail.includes('Net'),
  'sandboxed KiCad viewer supports real pad inspection and source-linked physical metadata');
 const report=await evaluate("document.getElementById('evidenceReport')?.getAttribute('href')");
 pass(report==='REVIEW_REPORT.html','native report stays a relative sandboxed evidence document');
 const reportRect=await evaluate("(()=>{const a=document.getElementById('evidenceReport');a.scrollIntoView({block:'center'});const box=a.getBoundingClientRect();return {x:box.left+box.width/2,y:box.top+box.height/2,width:box.width,height:box.height};})()");
 pass(reportRect.width>80&&reportRect.height>15&&reportRect.x>0&&reportRect.y>0,
  'native report link remains a usable desktop touch/mouse target');
 await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:reportRect.x,y:reportRect.y});
 await cmd('Input.dispatchMouseEvent',{type:'mousePressed',x:reportRect.x,y:reportRect.y,button:'left',clickCount:1});
 await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:reportRect.x,y:reportRect.y,button:'left',clickCount:1});
 let popup=null;
 for(let i=0;i<55;i++){
  const pages=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  popup=pages.find(item=>item.type==='page'&&item.id!==tab.id&&item.url?.includes('/REVIEW_REPORT.html'));
  if(popup)break;
  await new Promise(resolve=>setTimeout(resolve,115));
 }
 pass(!!popup,'registered sandboxed native reviewer can open the genuine evidence report in a separate local browser tab');
 await cmd('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 const mobileReview=await evaluate("(()=>{const a=document.getElementById('workspaceHome');return {href:a?.getAttribute('href'),visible:!!a&&getComputedStyle(a).display!=='none'&&a.getBoundingClientRect().width>30,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}})()");
 pass(mobileReview.href==='/'&&mobileReview.visible&&!mobileReview.overflow,
  '390px native reviewer exposes a usable Projects return link and no horizontal overflow');
 await evaluate("document.getElementById('workspaceHome').click()");
 let returned={};
 for(let i=0;i<70;i++){
  returned=await evaluate("(()=>({url:location.pathname,ready:document.readyState,count:document.querySelectorAll('.project').length,home:!!document.getElementById('workspaceProjects')}))()");
  if(returned.url==='/'&&returned.ready==='complete'&&returned.home)break;
  await new Promise(resolve=>setTimeout(resolve,125));
 }
 pass(returned.url==='/'&&returned.home&&returned.count===2,
  'mobile Projects action returns to original source-verified local review catalog without stale paths');
}
pass(errors.length===0,'zero real Chrome JavaScript errors: '+errors.join(' | '));
ws.close();console.log('WORKSPACE KEYBOARD AND ACCESSIBILITY: ALL PASSED');
