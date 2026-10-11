// Browser end-to-end: two native KiCad sources, catalog filtering and bidirectional navigation.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9810);
const shots=process.env.ZAPTRACE_WORKSPACE_SCREENSHOTS||'build/review-studio-workspace';
let pages;
for(let i=0;i<60;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}
 catch{}await new Promise(r=>setTimeout(r,140));
}
const p=pages?.find(p=>p.type==='page');if(!p)throw Error('Workspace browser page not available');
const ws=new WebSocket(p.webSocketDebuggerUrl);
await new Promise((ok,no)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',no,{once:true});});
let seq=0;const waiting=new Map(),errors=[],external=[];
ws.addEventListener('message',event=>{
 const m=JSON.parse(event.data);
 if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);
 if(m.method==='Network.requestWillBeSent'){
  const url=m.params?.request?.url;
  if(url&&/^(https?:)/i.test(url)&&!url.startsWith('http://127.0.0.1:'))external.push(url);
 }
 if(m.id&&waiting.has(m.id)){waiting.get(m.id)(m);waiting.delete(m.id);}
});
const call=(method,params={})=>new Promise((res,rej)=>{const id=++seq;waiting.set(id,r=>r.error?rej(Error(JSON.stringify(r.error))):res(r.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');await call('Page.enable');await call('Network.enable');
const js=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const verify=(v,description)=>{if(!v)throw Error('FAIL: '+description);console.log('PASS:',description);};
const waitFor=async expression=>{
 for(let i=0;i<60;i++){
  try{const data=await js(expression);if(data)return data;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 throw Error('Timeout waiting for browser navigation: '+expression);
};
const start=await js(`(()=>({url:location.href,count:document.querySelectorAll('.project').length,
 names:[...document.querySelectorAll('.project h3')].map(x=>x.textContent),
 blockers:[...document.querySelectorAll('.mini-metrics')].map(x=>x.textContent),
 links:[...document.querySelectorAll('.project .primary')].map(x=>x.href),
 negative:document.querySelector('.gate').textContent}))()`);
verify(start.url.includes('review-studio-workspace/index.html')&&start.count===2&&
 start.names[0].includes('copper')&&start.names[1].includes('unrouted')&&
 start.blockers[0].includes('16')&&start.blockers[0].includes('12')&&
 start.blockers[1].includes('42')&&start.blockers[1].includes('37')&&
 start.links.every(x=>x.startsWith('file:'))&&start.negative==='NOT FABRICATION APPROVED',
 'workspace renders two separately validated native PCB snapshots and correct actual DRC blockers');
const filtered=await js(`(()=>{const input=document.getElementById('filterProjects');
 input.value='unrouted';input.dispatchEvent(new Event('input'));
 const shown=[...document.querySelectorAll('.project')].filter(x=>!x.hidden).map(x=>x.querySelector('h3').textContent);
 const doc=document.documentElement;
 input.value='no-such-native-board';input.dispatchEvent(new Event('input'));
 const noResults=!document.getElementById('emptyFilter').hidden&&[...document.querySelectorAll('.project')].every(x=>x.hidden);
 input.value='';input.dispatchEvent(new Event('input'));
 return {shown,noResults,restored:[...document.querySelectorAll('.project')].every(x=>!x.hidden),
 overflow:doc.scrollWidth>doc.clientWidth};})()`);
verify(filtered.shown.length===1&&filtered.shown[0].includes('unrouted')&&filtered.noResults&&filtered.restored&&!filtered.overflow,
 'offline project filtering, empty result and reset work without horizontal overflow');
const homeImage=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/workspace-tested.png',Buffer.from(homeImage.data,'base64'));
const wizard=await js(`(()=>{
 const $=id=>document.getElementById(id),submit=()=>$('importForm').requestSubmit();
 $('importName').value="Alice's voltage sensor";
 $('importBoard').value="/home/user/board's rev.kicad_pcb";
 $('importSchematic').value="/home/user/board's rev.kicad_sch";
 submit();
 const cmd=$('importSnippet').textContent;
 const prepared=!$('preparedCommand').hidden;
 $('importBoard').value='relative/not-a-board.kicad_pcb';submit();
 const refused=$('preparedCommand').hidden&&$('importError').textContent.includes('absolute path');
 $('importBoard').value="/home/user/board's rev.kicad_pcb";submit();
 $('import').scrollIntoView({block:'start'});
 return {cmd,prepared,refused,restored:!$('preparedCommand').hidden,
  paths:cmd.includes('kicad_pcb')&&cmd.includes('kicad_sch'),
  malicious:cmd.includes("board's rev")};})()`);
console.log('OFFLINE KICAD IMPORT WIZARD',wizard);
verify(wizard.prepared&&wizard.refused&&wizard.restored&&wizard.paths&&
 wizard.cmd.includes('scripts/review_studio_workspace.py')&&wizard.cmd.includes('--board')&&
 wizard.cmd.includes('--schematic')&&wizard.cmd.includes('--name'),
 'form generates a local native KiCad command, refuses invalid relative paths, never claims browser-side import');
const wizardShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/workspace-import-wizard.png',Buffer.from(wizardShot.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobileWizard=await js(`(()=>{const doc=document.documentElement;
 document.getElementById('import').scrollIntoView({block:'start'});
 const box=document.getElementById('preparedCommand').getBoundingClientRect();
 return {width:doc.clientWidth,scroll:doc.scrollWidth,box:box.width,
  copy:document.getElementById('copyImport').getBoundingClientRect().width};})()`);
verify(mobileWizard.width<=390&&mobileWizard.scroll<=mobileWizard.width&&
 mobileWizard.box>0&&mobileWizard.box<=mobileWizard.width&&mobileWizard.copy>0,
 '390px mobile KiCad import wizard has readable command and no horizontal overflow');
const mobileShot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(shots+'/workspace-import-mobile.png',Buffer.from(mobileShot.data,'base64'));
await call('Emulation.clearDeviceMetricsOverride');
await js(`document.querySelector('.project .primary').click()`);
let first=await waitFor(`(()=>typeof DATA==='object'&&typeof DATA.source_sha256==='string'&&DATA.board.copper.length===61?{
 sha:DATA.source_sha256,copper:DATA.board.copper.length,opens:DATA.open_pairs.length,
 drc:DATA.findings.filter(f=>f.rule!=='unconnected_items').length,
 back:document.getElementById('workspaceHome')?.href,host:location.href}:false)()`);
verify(first.copper===61&&first.drc===16&&first.opens===12&&first.back?.includes('review-studio-workspace/index.html'),
 'first project card navigates into true 61-track KiCad preview with functioning projects backlink');
await js(`document.getElementById('workspaceHome').click()`);
await waitFor(`document.querySelectorAll('.project').length===2`);
await js(`document.querySelectorAll('.project .primary')[1].click()`);
let second=await waitFor(`(()=>typeof DATA==='object'&&typeof DATA.source_sha256==='string'&&DATA.board.copper.length===0?{
 sha:DATA.source_sha256,copper:DATA.board.copper.length,opens:DATA.open_pairs.length,
 drc:DATA.findings.filter(f=>f.rule!=='unconnected_items').length,
 back:document.getElementById('workspaceHome')?.href}:false)()`);
verify(second.sha!==first.sha&&second.copper===0&&second.drc===42&&second.opens===37&&
 second.back?.includes('review-studio-workspace/index.html'),
 'second project card navigates to different real unrouted KiCad source; 42 violations/37 open unwaived');
verify(errors.length===0&&external.length===0,'zero unexpected JavaScript exceptions or external network requests');
ws.close();console.log('MULTI-PROJECT NATIVE KICAD WORKSPACE: ALL PASSED');
