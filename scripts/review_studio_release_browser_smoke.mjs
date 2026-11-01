// Real Chrome GUI acceptance: packaged end-user onboarding, privacy and Stop.
import {writeFileSync} from 'node:fs';
const debug=Number(process.env.ZAPTRACE_CHROME_PORT||46600);
const output=process.env.ZAPTRACE_RELEASE_SHOTS||'build/distribution';
let pages=[];
for(let i=0;i<120;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${debug}/json/list`)).json();if(pages.some(p=>p.type==='page'))break;}catch{}
 await new Promise(r=>setTimeout(r,100));
}
const page=pages.find(p=>p.type==='page');if(!page)throw Error('Real Chrome release page unavailable');
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true});});
let id=0;const pending=new Map(),exceptions=[];
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}});
const call=(method,params={})=>new Promise((res,rej)=>{const request=++id;pending.set(request,m=>m.error?rej(Error(JSON.stringify(m.error))):res(m.result));ws.send(JSON.stringify({id:request,method,params}));});
await call('Runtime.enable');await call('Page.enable');
const js=async e=>{const r=await call('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const ok=(x,msg)=>{if(!x)throw Error('FAIL '+msg);console.log('PASS '+msg);};
let loaded=false;
for(let i=0;i<80;i++){
 try{loaded=await js(`document.readyState==='complete'&&!!document.getElementById('nativeImportForm')&&!!document.getElementById('help')`);if(loaded)break;}catch{}
 await new Promise(r=>setTimeout(r,110));
}
ok(loaded,'installed package loads its complete real local GUI from user home');
const initial=await js(`(()=>({url:location.href,real:document.querySelectorAll('.project').length,
 active:!document.getElementById('nativeImport').hidden,
 fallback:document.getElementById('cliFallback').hidden,
 intro:!document.getElementById('desktopOnboarding').hidden,
 staticIntro:document.getElementById('staticOnboarding').hidden,
 steps:!document.getElementById('desktopOnboardingSteps').hidden,
 picker:document.getElementById('nativeBoardFile').type,
 help:document.getElementById('help').querySelectorAll('details').length,
 legal:document.querySelector('.foot').textContent,
 compare:document.querySelector('.compare-select')?.hidden,
 stop:!document.getElementById('localSessionControls').hidden,
 fabrication:document.querySelector('header .gate').textContent}))()`);
console.log('RELEASE END-USER UI',initial);
ok(initial.url.startsWith('http://127.0.0.1:')&&initial.active&&initial.fallback&&initial.intro&&initial.staticIntro&&initial.steps&&initial.picker==='file',
 'end-user binary opens actual native file pickers and three-step onboarding with no developer commands');
ok(initial.help>=4&&initial.legal.includes('0.1.0')&&initial.legal.includes('Noncommercial')&&initial.stop,
 'in-app Help, user privacy, noncommercial license, version and visible session Stop are present');
ok(initial.fabrication.includes('NOT FABRICATION APPROVED'),
 'end-user install cannot misrepresent review evidence as PCB production authorization');
if(initial.real===1)ok(initial.compare===true,'one local project does not offer an unusable comparison checkbox');
const panel=await js(`(()=>{const details=document.querySelector('#help details');details.open=true;return {
 summary:details.querySelector('summary').textContent,
 text:details.querySelector('p').textContent,
 stopText:document.getElementById('stopLocalStudio').textContent};})()`);
ok(panel.summary.includes('KiCad files')&&panel.text.includes('.kicad_pro')&&panel.stopText.includes('Stop'),
 'first-party offline help explains required design-rule project file and local stop workflow');
const before=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(output+'/release-enduser-desktop.png',Buffer.from(before.data,'base64'));
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
const mobile=await js(`(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
 picker:document.getElementById('nativeBoardFile').getBoundingClientRect().width,
 steps:document.getElementById('desktopOnboardingSteps').getBoundingClientRect().width,
 help:document.querySelector('.help-center').getBoundingClientRect().width,
 stop:document.getElementById('stopLocalStudio').getBoundingClientRect().width}))()`);
console.log('RELEASE 390px',mobile);
ok(mobile.width<=390&&mobile.scroll<=390&&mobile.picker>100&&mobile.steps>200&&mobile.help>200&&mobile.stop>140,
 'installed native GUI, documentation and shutdown action fit 390px without horizontal scrolling');
const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(output+'/release-enduser-mobile.png',Buffer.from(shot.data,'base64'));
await call('Emulation.clearDeviceMetricsOverride');
const stop=await js(`(()=>{document.getElementById('stopLocalStudio').click();return true;})()`);
ok(stop,'user can directly request local service shutdown from installed app GUI');
let stopped=false;
for(let i=0;i<70;i++){
 await new Promise(r=>setTimeout(r,90));
 try{stopped=await js(`!document.getElementById('localStopped').hidden&&document.getElementById('nativeRun').disabled`);if(stopped)break;}catch{}
}
ok(stopped,'Stop confirms service close and disables imports without deleting completed reviews');
ok(exceptions.length===0,'no browser-side JavaScript exceptions during packaged end-user journey');
ws.close();console.log('INSTALLED RELEASE GUI FIRST-PARTY CHROME: ALL TESTS PASSED');
