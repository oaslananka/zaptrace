// Local Chrome DevTools smoke of REAL native KiCad PCB review; no network/upload.
import {writeFileSync} from 'node:fs';
const port=Number(process.env.ZAPTRACE_CHROME_PORT||9241);
const improved=process.env.ZAPTRACE_EXPECT_LAYOUT==='improved';
const expectPins=process.env.ZAPTRACE_EXPECT_PINS==='1';
const screenshotDir=process.env.ZAPTRACE_SCREENSHOT_DIR||'build/native-review';
let pages;
for(let i=0;i<55;i++){
 try{pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();if(pages.some(x=>x.type==='page'))break;}
 catch{}await new Promise(r=>setTimeout(r,150));
}
const p=pages?.find(x=>x.type==='page');if(!p)throw Error('Local Chrome debug page unavailable');
const ws=new WebSocket(p.webSocketDebuggerUrl);
await new Promise((ok,bad)=>{ws.addEventListener('open',ok,{once:true});ws.addEventListener('error',bad,{once:true});});
let seq=0;const callbacks=new Map(),errors=[];
ws.addEventListener('message',evt=>{const m=JSON.parse(evt.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);
 if(m.id&&callbacks.has(m.id)){callbacks.get(m.id)(m);callbacks.delete(m.id);}});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;callbacks.set(id,m=>m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result));ws.send(JSON.stringify({id,method,params}));});
await call('Runtime.enable');
const js=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
const check=(v,description)=>{if(!v)throw Error('FAIL '+description);console.log('PASS '+description);};
const initial=await js(`({parts:document.querySelectorAll('.fp-hit').length,pads:document.querySelectorAll('.pad-hit').length,
 faults:document.querySelectorAll('.fault').length,plots:document.querySelectorAll('.layerimage').length,tab:document.querySelectorAll('.listbutton').length,
 summary:document.getElementById('drcBadge').textContent,open:document.getElementById('openBadge').textContent,erc:document.getElementById('ercBadge').textContent,parity:document.getElementById('netParityBadge').textContent,
 physicalPin:document.getElementById('pinParityBadge').textContent,
 source:DATA.board_name,sha:DATA.source_sha256,kicad:DATA.board.kicad,segments:DATA.board.tracks})`);
console.log('KIcad real native evidence:',initial);
check(initial.parts===14&&initial.pads===112&&initial.faults===28&&initial.plots===7,'native plot: 14 footprints, 112 pads, 28 geolocated native DRC markers, seven KiCad layers');
check(initial.segments===61&&initial.summary.includes('16 findings')&&initial.open.includes('12 native')&&initial.erc.includes('0 findings')&&initial.parity.includes('7 net names')&&initial.parity.includes('pins unverified'),'independent native DRC 16 + 12 open, native ERC 0 enabled-check findings, 61 copper tracks');
const workspace=await js(`(async()=>{
 const $=id=>document.getElementById(id),metrics={drc:$('kpiDrc').textContent,
  opens:$('kpiOpens').textContent,erc:$('kpiErc').textContent,pins:$('kpiPins').textContent};
 $('quickDrc').click();const drc=document.querySelector('[data-tab="issues"]').getAttribute('aria-selected');
 $('quickOpen').click();const open=document.querySelector('[data-tab="opens"]').getAttribute('aria-selected');
 $('quickPins').click();const pins=document.querySelector('[data-tab="pins"]').getAttribute('aria-selected');
 $('quickErc').click();const schematic=$('modeSch').getAttribute('aria-pressed');$('modePcb').click();
 $('focusMode').click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 const focused={on:document.querySelector('.app').classList.contains('focus-mode'),
  hidden:getComputedStyle($('leftSidebar')).display==='none'&&getComputedStyle($('rightSidebar')).display==='none',
  canvas:$('boardspace').clientWidth};
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'q',bubbles:true}));
 await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 const normal={on:document.querySelector('.app').classList.contains('focus-mode'),
  canvas:$('boardspace').clientWidth};
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true}));
 const help={shown:!$('shortcutBackdrop').hidden,focus:document.activeElement.id};
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 const closed=$('shortcutBackdrop').hidden;
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'/',bubbles:true}));
 const searched=document.activeElement.id==='search';
 $('search').value='USB_CC1';document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 const cleared=$('search').value==='';$('search').blur();
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}));
 const shortcutPCB=$('modePcb').getAttribute('aria-pressed');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'2',bubbles:true}));
 const shortcutSch=$('modeSch').getAttribute('aria-pressed');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}));
 $('quickDrc').click();
 return {metrics,drc,open,pins,schematic,focused,normal,help,closed,searched,cleared,shortcutPCB,shortcutSch,
  inspector:$('inspectorCount').textContent};
})()`);
console.log('PRO WORKSPACE UI',workspace);
check(workspace.metrics.drc==='16'&&workspace.metrics.opens==='12'&&workspace.metrics.erc==='0'&&
 workspace.metrics.pins==='69/112'&&workspace.drc==='true'&&workspace.open==='true'&&
 workspace.pins==='true'&&workspace.schematic==='true',
 'professional evidence strip shows exact native oracle counts; all KPI links navigate to real findings');
check(workspace.focused.on&&workspace.focused.hidden&&workspace.focused.canvas>workspace.normal.canvas+300&&
 !workspace.normal.on,'canvas focus mode expands actual KiCad viewport and keyboard Q restores inspector');
check(workspace.help.shown&&workspace.help.focus==='closeHelp'&&workspace.closed&&workspace.searched&&
 workspace.cleared&&workspace.shortcutPCB==='true'&&workspace.shortcutSch==='true',
 'keyboard shortcuts dialog, Escape, quick search and PCB/schematic navigation operate in real Chrome');
check(workspace.inspector.includes('source findings'),'inspector source count remains tied to real native data');

const dockStart=await js(`(()=>{const $=id=>document.getElementById(id);
 const rect=$('leftSplitter').getBoundingClientRect();
 return {left:Math.round($('leftSidebar').getBoundingClientRect().width),
 right:Math.round($('rightSidebar').getBoundingClientRect().width),
 canvas:Math.round($('boardspace').getBoundingClientRect().width),
 x:Math.round(rect.left+rect.width/2),y:Math.round(rect.top+120)};})()`);
await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:dockStart.x,y:dockStart.y});
await call('Input.dispatchMouseEvent',{type:'mousePressed',x:dockStart.x,y:dockStart.y,button:'left',clickCount:1});
await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:dockStart.x+80,y:dockStart.y,button:'left',buttons:1});
await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:dockStart.x+80,y:dockStart.y,button:'left',clickCount:1});
const dockMoved=await js(`(()=>{const $=id=>document.getElementById(id);
 return {left:Math.round($('leftSidebar').getBoundingClientRect().width),
 right:Math.round($('rightSidebar').getBoundingClientRect().width),
 canvas:Math.round($('boardspace').getBoundingClientRect().width),
 announced:Number($('leftSplitter').getAttribute('aria-valuenow'))};})()`);
check(dockMoved.left>dockStart.left+60&&dockMoved.canvas<dockStart.canvas-60&&
 dockMoved.right===dockStart.right&&dockMoved.announced===dockMoved.left,
 'real desktop mouse drag resizes native evidence panel, preserves source object view and updates accessible value');
const dockPhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-resizable-panels.png',Buffer.from(dockPhoto.data,'base64'));
const dockKeyboard=await js(`(()=>{const $=id=>document.getElementById(id);
 const first=Math.round($('rightSidebar').getBoundingClientRect().width);
 const divider=$('rightSplitter');divider.focus();
 divider.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
 const adjusted=Math.round($('rightSidebar').getBoundingClientRect().width);
 divider.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
 const reset=Math.round($('rightSidebar').getBoundingClientRect().width);
 $('leftSplitter').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
 return {first,adjusted,reset,leftReset:Math.round($('leftSidebar').getBoundingClientRect().width),
 originalWidth:Math.round($('boardspace').getBoundingClientRect().width)};})()`);
check(dockKeyboard.adjusted===dockKeyboard.first+16&&
 dockKeyboard.reset===dockStart.right&&dockKeyboard.leftReset===dockStart.left&&
 Math.abs(dockKeyboard.originalWidth-dockStart.canvas)<2,
 'keyboard ArrowLeft and Home restore inspector dock; double-click resets evidence panel');
const queueEvidence=await js(`(()=>{const $=id=>document.getElementById(id);
 $('quickDrc').click();select({kind:'issue',index:0},true);
 const first={shown:!$('reviewQueue').hidden,status:$('reviewQueueStatus').textContent,
  prev:$('reviewPrev').disabled,next:$('reviewNext').disabled,selected:selected.index};
 $('reviewNext').click();const second={status:$('reviewQueueStatus').textContent,index:selected.index};
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',bubbles:true}));
 const back={index:selected.index,status:$('reviewQueueStatus').textContent};
 setTab('opens');const openFirst=DATA.open_pairs[0];
 select({kind:'issue',index:openFirst.finding_index},false);
 $('reviewNext').click();
 const open={shown:!$('reviewQueue').hidden,index:selected.index,
  status:$('reviewQueueStatus').textContent,overlay:document.querySelector('.airwire-overlay').querySelectorAll('line').length,
  total:DATA.open_pairs.length};
 const previousSelected=selected.index;
 $('search').value='I2C_SCL';$('search').dispatchEvent(new Event('input'));
 const scl=DATA.open_pairs.filter(pair=>pair.net==='I2C_SCL');
 select({kind:'issue',index:scl[0].finding_index},false);
 const filteredStart=$('reviewQueueStatus').textContent;
 $('reviewNext').click();
 const filteredNext={index:selected.index,status:$('reviewQueueStatus').textContent,
  lastDisabled:$('reviewNext').disabled,source:scl[1].finding_index};
 $('search').value='';$('search').dispatchEvent(new Event('input'));
 $('quickPins').click();const irrelevant=$('reviewQueue').hidden;
 return {first,second,back,open,irrelevant,previousSelected,filteredStart,filteredNext};})()`);
check(queueEvidence.first.shown&&queueEvidence.first.prev&&!queueEvidence.first.next&&
 queueEvidence.first.status.includes('1 of 28')&&queueEvidence.second.index===1&&
 queueEvidence.second.status.includes('2 of 28')&&queueEvidence.back.index===0&&
 queueEvidence.open.shown&&queueEvidence.open.status.includes('2 of 12')&&
 queueEvidence.open.overlay===1&&queueEvidence.irrelevant&&
 queueEvidence.filteredStart.includes('1 of 2 · filtered')&&
 queueEvidence.filteredNext.index===queueEvidence.filteredNext.source&&
 queueEvidence.filteredNext.status.includes('2 of 2 · filtered')&&
 queueEvidence.filteredNext.lastDisabled,
 'real DRC/physical-gap queue offers bounded previous/next navigation and J/K without claiming copper completion');
await js(`(()=>{setTab('issues');select({kind:'issue',index:1},true);})()`);
const queuePhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-review-queue.png',Buffer.from(queuePhoto.data,'base64'));
const commandStartup=await js(`(()=>{document.getElementById('searchWorkspace').click();
 const d=document.getElementById('commandBackdrop');
 return {open:!d.hidden,focused:document.activeElement.id==='commandInput',
  total:commandItems.length,rows:document.querySelectorAll('.command-result').length,
  first:document.querySelector('.command-result')?.textContent};})()`);
check(commandStartup.open&&commandStartup.focused&&commandStartup.total>200&&commandStartup.rows===35,
 'native object-wide command palette opens, focuses input and indexes only real objects');
const commandSearch=await js(`(()=>{const q=document.getElementById('commandInput');
 q.value='U1.33';q.dispatchEvent(new Event('input'));
 const rows=[...document.querySelectorAll('.command-result')];
 return {n:rows.length,first:rows[0]?.textContent,active:q.getAttribute('aria-activedescendant'),
  best:rows[0]?.querySelector('.command-type')?.textContent,warning:document.querySelector('.command-summary')?.textContent};})()`);
check(commandSearch.n>=1&&commandSearch.best==='PAD'&&commandSearch.first.includes('U1.33')&&
 commandSearch.active==='cmd-choice-0','command search ranks exact U1.33 native physical pad first');
const searchPhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-command-palette.png',Buffer.from(searchPhoto.data,'base64'));
const commandNavigate=await js(`(()=>{const input=document.getElementById('commandInput');
 input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
 return {closed:document.getElementById('commandBackdrop').hidden,
  tab:document.querySelector('[data-tab="pins"]').getAttribute('aria-selected'),
  selection:selected,expectedIndex:DATA.board.pads.findIndex(p=>p.ref==='U1'&&p.pad==='33'),
  detail:document.getElementById('detail').textContent,
  mode:document.getElementById('modePcb').getAttribute('aria-pressed')};})()`);
check(commandNavigate.closed&&commandNavigate.tab==='true'&&commandNavigate.mode==='true'&&
 commandNavigate.selection?.kind==='pad'&&commandNavigate.selection?.index===commandNavigate.expectedIndex&&
 commandNavigate.detail.includes('GPIO21'),
 'command Enter navigates to exact real pad and retains source cross-reference');
const commandNet=await js(`(()=>{document.getElementById('searchCanvas').click();
 const input=document.getElementById('commandInput');input.value='I2C_SCL';input.dispatchEvent(new Event('input'));
 const rows=[...document.querySelectorAll('.command-result')];const net=rows.find(r=>r.querySelector('.command-type')?.textContent==='NET');
 const found=!!net;net?.click();return {found,closed:document.getElementById('commandBackdrop').hidden,
  tab:document.querySelector('[data-tab="nets"]').getAttribute('aria-selected'),
  selection:selected,details:document.getElementById('detail').textContent};})()`);
check(commandNet.found&&commandNet.closed&&commandNet.tab==='true'&&
 commandNet.selection?.kind==='net'&&commandNet.selection?.net==='I2C_SCL',
 'command palette navigates to real native KiCad I2C_SCL net membership');
const commandOpen=await js(`(()=>{document.getElementById('searchCanvas').click();
 const input=document.getElementById('commandInput');input.value='open I2C_SCL';
 input.dispatchEvent(new Event('input'));const buttons=[...document.querySelectorAll('.command-result')];
 const candidate=buttons.find(x=>x.querySelector('.command-type')?.textContent==='OPEN');
 const count=buttons.filter(x=>x.querySelector('.command-type')?.textContent==='OPEN').length;
 candidate?.click();return {count,closed:document.getElementById('commandBackdrop').hidden,
  tab:document.querySelector('[data-tab="opens"]').getAttribute('aria-selected'),
  overlay:document.querySelector('.airwire-overlay').querySelectorAll('line').length,
  detail:document.getElementById('detail').textContent};})()`);
check(commandOpen.count===2&&commandOpen.closed&&commandOpen.tab==='true'&&commandOpen.overlay===1&&
 commandOpen.detail.includes('NOT a clearance-safe route'),
 'search finds two real I2C_SCL open DRC pairs and navigates to inspection-only airwire');
const commandClose=await js(`(()=>{document.dispatchEvent(new KeyboardEvent('keydown',{
 key:'k',ctrlKey:true,bubbles:true}));const opened=!document.getElementById('commandBackdrop').hidden;
 const q=document.getElementById('commandInput');q.value='no-such-native-ref-xyz';
 q.dispatchEvent(new Event('input'));
 const empty=document.getElementById('commandResults').textContent;
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 return {opened,empty,closed:document.getElementById('commandBackdrop').hidden,
  count:document.querySelectorAll('.command-result').length};})()`);
check(commandClose.opened&&commandClose.empty.includes('No matching native objects')&&
 commandClose.closed&&commandClose.count===0,
 'Ctrl+K, no-results disclosure and Escape close all work without fabricated search results');
const overlayReview=await js(`(()=>{const $=id=>document.getElementById(id),board=$('stage');
 const before={pad:board.querySelectorAll('.pad-hit').length,
  fault:board.querySelectorAll('.fault').length,footprint:board.querySelectorAll('.fp-hit').length,
  drc:$('kpiDrc').textContent,open:$('kpiOpens').textContent};
 for(const id of ['showPadMarkers','showFaultMarkers','showFootprintMarkers']){
  $(id).checked=false;$(id).dispatchEvent(new Event('change'));
 }
 const hidden={pads:getComputedStyle(board.querySelector('.pad-hit')).display,
  faults:getComputedStyle(board.querySelector('.fault')).display,
  footprints:getComputedStyle(board.querySelector('.fp-hit')).display,
  drc:$('kpiDrc').textContent,open:$('kpiOpens').textContent};
 for(const id of ['showPadMarkers','showFaultMarkers','showFootprintMarkers']){
  $(id).checked=true;$(id).dispatchEvent(new Event('change'));
 }
 const restored={pads:getComputedStyle(board.querySelector('.pad-hit')).display,
  faults:getComputedStyle(board.querySelector('.fault')).display,
  footprints:getComputedStyle(board.querySelector('.fp-hit')).display};
 $('modeSch').click();const hiddenOnSchematic=$('inspectionOverlays').hidden;
 $('modePcb').click();return {before,hidden,restored,hiddenOnSchematic};})()`);
check(overlayReview.before.pad===112&&overlayReview.before.fault===28&&
 overlayReview.before.footprint===14&&overlayReview.hidden.pads==='none'&&
 overlayReview.hidden.faults==='none'&&overlayReview.hidden.footprints==='none'&&
 overlayReview.hidden.drc==='16'&&overlayReview.hidden.open==='12'&&
 overlayReview.restored.pads!=='none'&&overlayReview.restored.faults!=='none'&&
 overlayReview.restored.footprints!=='none'&&overlayReview.hiddenOnSchematic,
 'inspection overlays can be hidden/restored without changing native DRC/continuity evidence');
const commandArrowFocus=await js(`(()=>{document.getElementById('searchCanvas').click();
 const input=document.getElementById('commandInput');input.value='J1.';input.dispatchEvent(new Event('input'));
 const first=input.getAttribute('aria-activedescendant');
 input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
 const next=input.getAttribute('aria-activedescendant');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));
 const closeFocus=document.activeElement.id;
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,shiftKey:true}));
 const returnedFocus=document.activeElement.id;
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 return {first,next,closeFocus,returnedFocus,closed:document.getElementById('commandBackdrop').hidden};})()`);
check(commandArrowFocus.first==='cmd-choice-0'&&commandArrowFocus.next==='cmd-choice-1'&&
 commandArrowFocus.closeFocus==='closeCommand'&&commandArrowFocus.returnedFocus==='commandInput'&&
 commandArrowFocus.closed,'native command search supports ArrowDown and keyboard-accessible close control');
const cursorNative=await js(`(()=>{const pad=DATA.board.pads.find(x=>x.ref==='U1'&&x.pad==='33');
 const rect=document.getElementById('boardspace').getBoundingClientRect();
 const x=rect.left+panX+(pad.x-DATA.plot_origin[0])*SCALE*zoom;
 const y=rect.top+panY+(pad.y-DATA.plot_origin[1])*SCALE*zoom;
 document.getElementById('boardspace').dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:x,clientY:y}));
 const display=document.getElementById('footright').textContent;
 document.getElementById('boardspace').dispatchEvent(new PointerEvent('pointerleave',{bubbles:true}));
 return {display,reset:document.getElementById('footright').textContent};})()`);
check(cursorNative.display.includes('Cursor')&&
 cursorNative.display.includes('mm')&&
 cursorNative.reset.includes('move cursor'),
 'native viewport cursor tracks pcbnew millimetre coordinates and clears outside the board');

if(expectPins){
 check(initial.physicalPin.includes('69/112 mapped')&&initial.physicalPin.includes('0 mismatch'),
  'physical pin-to-pad correspondence checked against design source for 69 pads, 43 intentionally unmapped');
 const nativeMapping=await js(`({status:DATA.pin_parity.state,count:DATA.pin_parity.mapped_pad_instances,
  notMapped:DATA.pin_parity.unmapped_pad_instances,nativePins:DATA.pin_parity.schematic_logical_pin_nodes,
  inputSHA:DATA.pin_parity.design_sha256,sample:DATA.pin_parity.pad_links.find(i=>i.ref==='U1'&&i.pad==='33')})`);
 check(nativeMapping.status==='mapped_net_consistent'&&nativeMapping.count===69&&
  nativeMapping.notMapped===43&&nativeMapping.nativePins===37&&nativeMapping.inputSHA.length===64&&
  nativeMapping.sample.logical_pin==='GPIO21'&&nativeMapping.sample.net==='I2C_SDA',
  'native physical pad U1.33 cross-checked to canonical GPIO21 and native KiCad SDA');
 let padSelection=await js(`(()=>{const match=[...document.querySelectorAll('.pad-hit')].find(e=>e.title.startsWith('U1.33 '));
  match.click();return document.getElementById('detail').textContent})()`);
 check(padSelection.includes('Authored logical pin')&&padSelection.includes('GPIO21')&&
  padSelection.includes('NOT qualified'),'pad inspector exposes mapped logical pin with supplier/continuity nonclaim');
 padSelection=await js(`(()=>{const match=[...document.querySelectorAll('.pad-hit')].find(e=>e.title.startsWith('J1.A6 '));
  match.click();return document.getElementById('detail').textContent})()`);
 check(padSelection.includes('outside the authored mapping')&&!padSelection.includes('Authored logical pin'),
  'unmapped USB-C pad explicitly not represented as checked');
 const explorer=await js(`(()=>{document.querySelector('[data-tab="pins"]').click();
  const totalGroups=document.querySelectorAll('.issuegroup').length;
  document.getElementById('search').value='GPIO21';document.getElementById('search').dispatchEvent(new Event('input'));
  const rows=[...document.querySelectorAll('.issuebody .listbutton')];
  const mapped=rows.length===1&&rows[0].textContent.includes('U1.33')&&rows[0].textContent.includes('Matched authored map');
  rows[0]?.click();return {totalGroups,mapped,logical:document.getElementById('detail').textContent}})()`);
 check(explorer.totalGroups===14&&explorer.mapped&&explorer.logical.includes('GPIO21'),
  'Pins explorer groups 112 physical pads into 14 components and finds verified-against-source U1.33');
 const noMap=await js(`(()=>{document.getElementById('search').value='J1.A6';
  document.getElementById('search').dispatchEvent(new Event('input'));
  const rows=[...document.querySelectorAll('.issuebody .listbutton')];
  const state=rows.map(x=>x.textContent);rows[0]?.click();
  return {rows:rows.length,state,detail:document.getElementById('detail').textContent}})()`);
 check(noMap.rows===1&&noMap.state[0].includes('Unmapped / not qualified')&&
  noMap.detail.includes('No pin-to-pad approval'),
  'Pins explorer makes excluded USB-C A6 inspectable without implying qualification');
 const brokenBadge=await js(`(()=>{const model=DATA.pin_parity;
  const previous={state:model.state,count:model.mismatch_count,mismatches:model.mismatches};
  model.state='mismatch';model.mismatch_count=1;
  model.mismatches=[{ref:'J1',pad:'A5',reason:'physical-pad-versus-schematic-net',expected:'USB_CC1',actual:'GND'}];
  summary();document.querySelector('[data-tab="pins"]').click();
  const text=document.getElementById('pinParityBadge').textContent;
  const blocked=document.getElementById('entrylist').textContent.includes('PIN MAPPING BLOCKER');
  const risky=document.getElementById('pinParityBadge').className.includes('critical');
  Object.assign(model,{state:previous.state,mismatch_count:previous.count,mismatches:previous.mismatches});
  summary();return {text,blocked,risky,restored:document.getElementById('pinParityBadge').textContent};})()`);
 check(brokenBadge.text.includes('1 mismatches')&&brokenBadge.blocked&&brokenBadge.risky&&
  brokenBadge.restored.includes('0 mismatch'),
  'injected pin-map mismatch visibly blocks approval and source-safe state restores afterward');


}
const manualMeasure=await js(`(()=>{const pads=DATA.board.pads,ia=pads.findIndex(p=>p.ref==='U1'&&p.pad==='33');
 const ib=pads.findIndex(p=>p.ref==='U2'&&p.pad==='3');
 document.getElementById('measure').click();
 select({kind:'pad',index:ia},false);
 const once={n:measurePoints.length,on:measureOn};
 select({kind:'pad',index:ia},false);
 const dup={n:measurePoints.length,on:measureOn};
 select({kind:'pad',index:ib},false);
 const expected=Math.hypot(pads[ib].x-pads[ia].x,pads[ib].y-pads[ia].y);
 const done={n:measurePoints.length,on:measureOn,readout:document.getElementById('measureReadout').textContent,
  lines:document.querySelectorAll('.measure-overlay line').length,anchors:document.querySelectorAll('.measure-overlay circle').length,
  pressed:document.getElementById('measure').getAttribute('aria-pressed')};
 document.getElementById('clearMeasure').click();
 const cleared={n:measurePoints.length,lines:document.querySelectorAll('.measure-overlay line').length,
  pressed:document.getElementById('measure').getAttribute('aria-pressed')};
 return {once,dup,expected,done,cleared};})()`);
console.log('NATIVE PAD MEASUREMENT',manualMeasure);
check(manualMeasure.once.n===1&&manualMeasure.dup.n===1&&manualMeasure.done.n===2&&
 !manualMeasure.done.on&&manualMeasure.done.lines===1&&manualMeasure.done.anchors===2&&
 manualMeasure.done.pressed==='false'&&manualMeasure.done.readout.includes(manualMeasure.expected.toFixed(4)+' mm')&&
 manualMeasure.done.readout.includes('NOT copper-to-copper clearance')&&manualMeasure.cleared.n===0&&
 manualMeasure.cleared.lines===0&&manualMeasure.cleared.pressed==='false',
 'real pad-to-pad Euclidean center measurement, duplicate rejected, disclaimer and reset in Chrome');
const localReport=await js(`({href:document.getElementById('evidenceReport').getAttribute('href'),
 visible:!!document.getElementById('evidenceReport').getBoundingClientRect().width})`);
check(localReport.href==='REVIEW_REPORT.html'&&localReport.visible,
 'user-accessible local evidence report link displayed with source-only file URL');
const schPins=await js(`({pinCount:DATA.schematic.pin_anchors.length,markers:document.querySelectorAll('.sch-pin-hit').length,
 nativeSource:DATA.schematic.pin_anchors.every(p=>p.source.includes('embedded KiCad library'))})`);
check(schPins.pinCount===37&&schPins.markers===37&&schPins.nativeSource,
 '37 real native Eeschema logical pin endpoint markers, no approximate component-centre pin positions');
const pinRoundtrip=await js(`(()=>{const pad=[...document.querySelectorAll('.pad-hit')].find(e=>e.title.startsWith('U1.33 '));
 pad.click();const toSch=[...document.querySelectorAll('#detail .crossnav')]
 .find(e=>e.textContent.includes('Locate exact schematic pin U1.GPIO21'));
 if(!toSch)return {found:false};toSch.click();
 const onSch=document.querySelector('.sch-pin-hit.selected');
 const first={ref:onSch?.dataset.ref,pin:onSch?.dataset.pin,detail:document.getElementById('detail').textContent,
  schMode:document.getElementById('modeSch').getAttribute('aria-pressed')};
 const toPcb=[...document.querySelectorAll('#detail .crossnav')]
 .find(e=>e.textContent.includes('Go to native PCB U1.33'));
 if(!toPcb)return {found:false,first};toPcb.click();
 return {found:true,first,mode:document.getElementById('modePcb').getAttribute('aria-pressed'),
  selected:document.querySelectorAll('.pad-hit.selected').length};})()`);
check(pinRoundtrip.found&&pinRoundtrip.first.ref==='U1'&&pinRoundtrip.first.pin==='GPIO21'&&
 pinRoundtrip.first.schMode==='true'&&pinRoundtrip.first.detail.includes('I2C_SDA')&&
 pinRoundtrip.mode==='true'&&pinRoundtrip.selected===1,
 'native PCB U1.33 ↔ exact Eeschema U1.GPIO21 pin endpoint (not symbol centre)');
const usbcMultiPin=await js(`(()=>{document.getElementById('modeSch').click();
 const btn=[...document.querySelectorAll('.sch-pin-hit')].find(b=>b.dataset.ref==='J1'&&b.dataset.pin==='VBUS');
 btn?.click();return {found:!!btn,selected:document.querySelector('.sch-pin-hit.selected')?.dataset.pin,
  padLinks:[...document.querySelectorAll('#detail .crossnav')].filter(x=>x.textContent.includes('Go to native PCB J1.')).map(x=>x.textContent)};})()`);
check(usbcMultiPin.found&&usbcMultiPin.selected==='VBUS'&&usbcMultiPin.padLinks.length===4&&
 usbcMultiPin.padLinks.some(x=>x.includes('J1.B9')),
 'J1.VBUS schematic pin exposes all four original USB-C VBUS pads, no fake one-to-one mapping');
const pinPhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/native-schematic-pin-crossprobe.png',Buffer.from(pinPhoto.data,'base64'));
let opens=await js(`(()=>{document.getElementById('modePcb').click();const issue=[...document.querySelectorAll('.fault')]
 .find(x=>x.title.startsWith('unconnected_items'));issue.click();
 const svg=document.querySelector('.airwire-overlay');const pair=DATA.open_pairs.find(p=>String(p.finding_index)===svg.dataset.showing);
 return {total:DATA.open_pairs.length,open:!!pair,lines:svg.querySelectorAll('line').length,
  ends:svg.querySelectorAll('circle').length,buttons:[...document.querySelectorAll('#detail .crossnav')]
   .filter(b=>b.textContent.includes('Focus native')).length,warning:document.getElementById('detail').textContent,
  separation:pair?.straight_line_mm};})()`);
console.log('NATIVE_REAL_DRC_OPEN_AIRWIRE',opens);
check(opens.total===12&&opens.open&&opens.lines===1&&opens.ends===2&&opens.buttons===2&&
 opens.warning.includes('inspection-only airwire')&&opens.warning.includes('NOT a clearance-safe route')&&opens.separation>0,
 '12 native KiCad open pairs; each selected gap overlays validated two-endpoint dashed inspection airwire, not route');
const openExplorer=await js(`(()=>{document.getElementById('inspectOpens').click();
 const all=document.querySelectorAll('#entrylist .issuegroup');
 const total=[...document.querySelectorAll('#entrylist .issuebody .listbutton')];
 const names=[...all].map(x=>x.querySelector('.issuetitle')?.textContent);
 document.getElementById('search').value='I2C_SCL';
 document.getElementById('search').dispatchEvent(new Event('input'));
 const filtered=[...document.querySelectorAll('#entrylist .issuebody .listbutton')];
 filtered[0]?.click();
 return {tab:document.querySelector('[data-tab="opens"]').getAttribute('aria-selected'),
  groups:all.length,count:total.length,names,filtered:filtered.length,
  overlay:document.querySelector('.airwire-overlay').dataset.showing,
  notes:document.getElementById('detail').textContent};})()`);
check(openExplorer.tab==='true'&&openExplorer.groups===4&&openExplorer.count===12&&
 openExplorer.names.some(n=>n.includes('I2C_SCL'))&&openExplorer.filtered===2&&
 openExplorer.overlay&&openExplorer.notes.includes('NOT a clearance-safe route'),
 'Open tab groups 12 verified KiCad gaps across four actual nets, filters and frames source endpoints');
const inspectorLayout=await js(`(()=>{const d=document.getElementById('detail'),l=document.getElementById('entrylist');
 const view=document.getElementById('boardspace');return {detailClient:d.clientHeight,detailScroll:d.scrollHeight,
 listClient:l.clientHeight,listScroll:l.scrollHeight,canvas:view.clientHeight}})()`);
check(inspectorLayout.listClient>=115&&inspectorLayout.listClient>0&&inspectorLayout.detailClient<=375&&
 inspectorLayout.canvas>400,
 'desktop inspector keeps a separately scrollable open-connection list visible beside detailed fault evidence');
const openPhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/native-open-connections.png',Buffer.from(openPhoto.data,'base64'));
opens=await js(`(()=>{const btn=[...document.querySelectorAll('#detail .crossnav')].find(x=>x.textContent.includes('Frame both open-connection'));
 btn.click();const showing=document.querySelector('.airwire-overlay').dataset.showing;
 const coords=document.getElementById('stage').style.transform;
 const other=[...document.querySelectorAll('.fault')].find(e=>e.title.startsWith('drill_out_of_range'));
 other.click();return {showing,coords,cleared:document.querySelector('.airwire-overlay').querySelectorAll('line').length===0};})()`);
check(opens.showing&&opens.coords.includes('scale')&&opens.cleared,
 'frame both actual gap endpoints and clear provisional airwire when inspecting another DRC rule');
let info=await js(`(()=>{const e=document.querySelector('.fault');e.click();return {selected:document.querySelector('.fault.selected')!==null,detail:document.getElementById('detail').textContent,transform:document.getElementById('stage').style.transform}})()`);
check(info.selected&&info.detail.includes('drill_out_of_range')&&info.detail.includes('Next safe action')&&info.detail.includes('Do not silently relax')&&info.transform.includes('scale'),'clicking native KiCad DRC marker inspects correct rule and pans');
// A reported pad should resolve only when native ref, pad number AND position match.
let drcPad=await js(`(()=>{const issue=[...document.querySelectorAll('.fault')].find(b=>b.title.startsWith('drill_out_of_range'));
 issue.click();const buttons=[...document.querySelectorAll('#detail .crossnav')];const target=buttons.find(b=>b.textContent.includes('Inspect native pad U1.39'));
 if(!target)return {found:false,links:buttons.map(b=>b.textContent)};target.click();return {
 found:true,text:document.getElementById('detail').textContent,selected:document.querySelectorAll('.pad-hit.selected').length,
 correct:DATA.board.pads.filter(x=>x.ref==='U1'&&x.pad==='39').length};})()`);
check(drcPad.found&&drcPad.selected===1&&drcPad.text.includes('U1 / pad 39')&&drcPad.correct>1,
 'native DRC thermal pad links via exact ref, pad number, mm coordinates, avoiding ambiguous duplicate pad-39');
let usb=await js(`(()=>{const issue=[...document.querySelectorAll('.fault')].find(b=>b.title.startsWith('hole_clearance'));
 issue.click();const b=[...document.querySelectorAll('#detail .crossnav')].find(x=>x.textContent.includes('Inspect native pad J1.A1'));
 if(!b)return {found:false,links:[...document.querySelectorAll('#detail .crossnav')].map(x=>x.textContent)};
 b.click();return {found:true,detail:document.getElementById('detail').textContent,selected:document.querySelectorAll('.pad-hit.selected').length};})()`);
check(usb.found&&usb.selected===1&&usb.detail.includes('J1 / pad A1'),
 'native USB-C hole clearance links to exact original J1.A1 source pad');
info=await js(`(()=>{document.querySelector('[data-tab="parts"]').click();document.getElementById('search').value='U1';document.getElementById('search').dispatchEvent(new Event('input'));const n=document.querySelectorAll('.listbutton').length;document.querySelector('.listbutton').click();return {count:n,detail:document.getElementById('detail').textContent,selected:document.querySelector('.fp-hit.selected')!==null}})()`);
check(info.count===1&&info.detail.includes('U1')&&info.selected,'part search opens actual KiCad footprint and pad list');
info=await js(`(()=>{const e=[...document.querySelectorAll('.pad-hit')].find(n=>n.title.startsWith('U1.1 '));e.click();return {text:document.getElementById('detail').textContent,selected:document.querySelector('.pad-hit.selected')!==null}})()`);
check(info.selected&&info.text.includes('GND')&&info.text.includes('Pad size'),'native pad number, net, physical pad dimensions accessible');
info=await js(`(()=>{const e=[...document.querySelectorAll('.layers input')].find(x=>x.getAttribute('aria-label')==='Show F.Cu');e.click();return {checked:e.checked,display:[...document.querySelectorAll('.layerimage')].find(x=>x.dataset.layer==='F.Cu').style.display}})()`);
check(!info.checked&&info.display==='none','front copper layer really hides native KiCad plot');
info=await js(`(()=>{document.querySelector('[data-tab="nets"]').click();document.getElementById('search').value='I2C_SDA';document.getElementById('search').dispatchEvent(new Event('input'));const c=document.querySelectorAll('.listbutton').length;document.querySelector('.listbutton').click();return {count:c,contents:document.getElementById('detail').textContent}})()`);
check(info.count===1&&info.contents.includes('I2C_SDA'),'real pad net membership search/inspect');
info=await js(`(()=>{document.getElementById('inspectIssues').click();return {selected:document.querySelector('[data-tab="issues"]').getAttribute('aria-selected'),focus:document.activeElement.id}})()`);
check(info.selected==='true'&&info.focus==='entrylist','readiness CTA navigates and focuses actual DRC findings');
// Verify the formerly clipped source symbols and bidirectional crossprobe.
let mapping=await js(`({n:DATA.schematic.symbols.length,anchors:document.querySelectorAll('.sch-hit').length,
 cross:DATA.schematic.crossprobe_refs.length,a2:DATA.schematic.display_page_expanded,
 page:DATA.schematic.viewbox,far:DATA.schematic.symbols.find(s=>s.ref==='J1')?.x})`);
check(mapping.n===14&&mapping.anchors===14&&mapping.cross===14&&
 (improved?(!mapping.a2&&mapping.page[0]>410&&mapping.page[0]<430&&mapping.far>310&&mapping.far<420)
           :(mapping.a2&&mapping.page[0]>590&&mapping.far>400)),
 improved?'all 14 refs fit native generated A3 (no post-hoc resize)':'14 refs fit display-only A2 expansion of original');
let cross=await js(`(()=>{document.querySelector('[data-tab="parts"]').click();document.getElementById('search').value='J1';
 document.getElementById('search').dispatchEvent(new Event('input'));document.querySelector('.listbutton').click();
 const go=[...document.querySelectorAll('#detail .crossnav')].find(x=>x.textContent.includes('Find J1 in native schematic'));
 if(!go)return {found:false};go.click();return {found:true,mode:document.getElementById('modeSch').getAttribute('aria-pressed'),
 focus:document.querySelector('.sch-hit.selected')?.dataset.ref,zoom:zoom}})()`);
check(cross.found&&cross.mode==='true'&&cross.focus==='J1'&&cross.zoom>=1.1,
 'PCB J1 → native schematic J1 direct true-ref crossprobe beyond original A4 page');
let sheetPanel=await js(`({copperHidden:document.getElementById('copperControls').hidden,
 schematicVisible:!document.getElementById('schematicContext').hidden,
 evidence:document.getElementById('schematicContextText').textContent})`);
check(sheetPanel.copperHidden&&sheetPanel.schematicVisible&&
 (expectPins?sheetPanel.evidence.includes('69 mapped pad instances'):true),
 'schematic mode replaces PCB copper controls with scoped schematic evidence');
const focusImage=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/crossprobe-J1-schematic.png',Buffer.from(focusImage.data,'base64'));
cross=await js(`(()=>{const x=document.querySelector('.sch-hit[data-ref="U1"]');x.click();
 const go=[...document.querySelectorAll('#detail .crossnav')].find(b=>b.textContent.includes('Jump to PCB footprint U1'));
 if(!go)return {found:false};go.click();return {found:true,mode:document.getElementById('modePcb').getAttribute('aria-pressed'),
 selected:DATA.board.footprints[DATA.board.footprints.findIndex(f=>f.ref==='U1')].ref,
 hit:document.querySelectorAll('.fp-hit.selected').length}})()`);
check(cross.found&&cross.mode==='true'&&cross.selected==='U1'&&cross.hit===1,
 'schematic U1 → real PCB U1 crossprobe and physical pan');
// Ensure crossprobe is exact reference matching, not fabricated proximity on PCB.
let net=await js(`(()=>{const copper=[...document.querySelectorAll('.layers input')].find(x=>x.getAttribute('aria-label')==='Show F.Cu');
 if(!copper.checked)copper.click();document.querySelector('[data-tab="nets"]').click();document.getElementById('search').value='I2C_SDA';
 document.getElementById('search').dispatchEvent(new Event('input'));document.querySelector('.listbutton').click();
 return {chosen:selected.net,rendered:+document.querySelector('.net-overlay').dataset.segmentCount,
 expected:DATA.board.copper.filter(t=>t.net==='I2C_SDA'&&visible[t.layer]).length,
 pads:+document.querySelector('.net-overlay').dataset.padCount,
 expectedPads:DATA.board.pads.filter(p=>p.net==='I2C_SDA').length,
 caveat:document.getElementById('detail').textContent.includes('NOT demonstrated')}})()`);
console.log('NATIVE_COPPER_HIGHLIGHT',net);
check(net.chosen==='I2C_SDA'&&net.rendered===net.expected&&net.rendered>0&&
 net.pads===net.expectedPads&&net.caveat,'selected native SDA net overlays every native copper segment and pad, with continuity nonclaim');
let copperLayer=await js(`(()=>{const el=[...document.querySelectorAll('.layers input')].find(x=>x.getAttribute('aria-label')==='Show F.Cu');
 el.click();return {rendered:+document.querySelector('.net-overlay').dataset.segmentCount,
 expected:DATA.board.copper.filter(t=>t.net==='I2C_SDA'&&visible[t.layer]).length}})()`);
check(copperLayer.rendered===copperLayer.expected,'copper highlights respect hidden source layers');
let modes=await js(`(()=>{document.getElementById('modeSch').click();return {active:document.getElementById('modeSch').getAttribute('aria-pressed'),visible:document.querySelector('.schstage').style.display, pcb:document.getElementById('stage').style.display,alt:document.querySelector('.schstage img').alt,loaded:document.querySelector('.schstage img').naturalWidth};})()`);
check(modes.active==='true'&&modes.visible==='block'&&modes.pcb==='none'&&modes.loaded>0,'native KiCad schematic image loads and switches without fabricated ERC result');
const allSchematic=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/native-schematic-all.png',Buffer.from(allSchematic.data,'base64'));
const snap=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync('build/real-esp32-copper-local/native-schematic.png',Buffer.from(snap.data,'base64'));
modes=await js(`(()=>{document.getElementById('modePcb').click();return {pressed:document.getElementById('modePcb').getAttribute('aria-pressed'),plot:document.getElementById('stage').style.display}})()`);
check(modes.pressed==='true'&&modes.plot==='block','returns to interactive native PCB view');
await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
info=await js(`({cw:document.documentElement.clientWidth,sw:document.documentElement.scrollWidth,canvas:document.getElementById('boardspace').clientHeight})`);
console.log('MOBILE',info);
check(info.cw===390&&info.sw<=392&&info.canvas>=450,'390px layout usable without horizontal overflow');
const mobileHierarchy=await js(`({canvasTop:document.getElementById('boardspace').getBoundingClientRect().top,
 evidenceTop:document.getElementById('leftSidebar').getBoundingClientRect().top,
 healthTop:document.querySelector('.healthbar').getBoundingClientRect().top,
 healthRows:document.querySelectorAll('.health-stat').length})`);
const mobileDock=await js(`(()=>({left:getComputedStyle(document.getElementById('leftSplitter')).display,
 right:getComputedStyle(document.getElementById('rightSplitter')).display,
 queue:document.getElementById('reviewQueue').hidden}))()`);
check(mobileDock.left==='none'&&mobileDock.right==='none',
 '390px mobile removes decorative resize handles without losing native inspection functionality');
check(mobileHierarchy.canvasTop<mobileHierarchy.evidenceTop&&mobileHierarchy.healthTop<mobileHierarchy.canvasTop&&
 mobileHierarchy.healthRows===4,'390px mobile hierarchy prioritizes PCB before detailed evidence with four real check metrics');
const mobileCommand=await js(`(()=>{document.getElementById('searchCanvas').click();
 const input=document.getElementById('commandInput');input.value='J1.A5';
 input.dispatchEvent(new Event('input'));
 const doc=document.documentElement;
 const result=document.querySelector('.command-result');
 const dlg=document.querySelector('.command-dialog').getBoundingClientRect();
 return {open:!document.getElementById('commandBackdrop').hidden,match:result?.textContent,
  scroll:doc.scrollWidth,width:doc.clientWidth,dialogWidth:dlg.width,
  buttonVisible:document.getElementById('closeCommand').getBoundingClientRect().width>0};})()`);
check(mobileCommand.open&&mobileCommand.match.includes('J1.A5')&&
 mobileCommand.dialogWidth<=390&&mobileCommand.scroll<=390&&mobileCommand.buttonVisible,
 '390px command search remains usable without horizontal overflow or obscured close action');
const mobileCommandImage=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-command-mobile.png',Buffer.from(mobileCommandImage.data,'base64'));
await js(`(()=>{document.getElementById('closeCommand').click()})()`);
const mobilePhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-mobile.png',Buffer.from(mobilePhoto.data,'base64'));

const gestureStart=await js(`(()=>{const r=document.getElementById('boardspace').getBoundingClientRect();
 return {x:Math.floor(r.left),y:Math.floor(r.top),height:r.height,zoom,panX,panY};})()`);
await call('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:2});
const yTouch=Math.min(760,Math.round(gestureStart.y+gestureStart.height*.57));
await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:115,y:yTouch,id:31}]});
await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:158,y:yTouch+24,id:31}]});
const oneFinger=await js(`({panX,panY,active:activePointers.size,kind:pointer?.kind})`);
console.log('MOBILE PAN INPUT',gestureStart,oneFinger);
await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
check(oneFinger.panX>gestureStart.panX+30&&oneFinger.panY>gestureStart.panY+14&&
 oneFinger.active===1&&oneFinger.kind==='pan'&&await js('activePointers.size')===0,
 'actual one-finger touch moves canvas without changing native geometry or leaving captured pointers');
await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:118,y:yTouch,id:1},{x:260,y:yTouch,id:2}]});
await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:66,y:yTouch-8,id:1},{x:312,y:yTouch+8,id:2}]});
const gestureZoom=await js(`({zoom,active:activePointers.size,kind:pointer?.kind})`);
await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
const gestureStop=await js(`({zoom,active:activePointers.size,kind:pointer?.kind})`);
console.log('NATIVE MOBILE PINCH',gestureStart.zoom,gestureZoom,gestureStop);
check(gestureZoom.zoom>gestureStart.zoom*1.25&&gestureZoom.active===2&&gestureZoom.kind==='pinch'&&
 gestureStop.active===0&&!gestureStop.kind,
 'actual Chrome touch input pinches native PCB viewport around two-finger midpoint and releases capture cleanly');
const pinchImage=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/professional-mobile-pinch.png',Buffer.from(pinchImage.data,'base64'));
const isolatedPad=await js(`(()=>{document.getElementById('fit').click();
 const i=DATA.board.pads.findIndex(p=>p.ref==='U3'&&p.pad==='2'&&p.x>65);
 const p=DATA.board.pads[i],rect=viewport.getBoundingClientRect(),hit=focusButtons.pads[i].getBoundingClientRect();
 const x=rect.left+panX+(p.x-DATA.plot_origin[0])*SCALE*zoom;
 const y=rect.top+panY+(p.y-DATA.plot_origin[1])*SCALE*zoom;
 return {index:i,x:Math.round(x),y:Math.round(y),diameter:hit.width,
  drift:Math.hypot((hit.left+hit.width/2)-x,(hit.top+hit.height/2)-y)};})()`);
check(isolatedPad.diameter>=22&&isolatedPad.drift<1.1,
 'native pad hitbox retains 24px touch size with physical center accuracy at fitted zoom');
await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:isolatedPad.x,y:isolatedPad.y,id:21}]});
await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
const tapSelection=await js(`({selected,detail:document.getElementById('detail').textContent})`);
check(tapSelection.selected?.kind==='pad'&&tapSelection.selected.index===isolatedPad.index&&
 tapSelection.detail.includes('U3 / pad 2'),
 'actual mobile touch at calibrated native pad hotspot selects the correct physical KiCad pad');
await call('Emulation.setTouchEmulationEnabled',{enabled:false});

check(errors.length===0,'zero uncaught JS exceptions across browser interactions');
await call('Emulation.clearDeviceMetricsOverride');
const visualMeasure=await js(`(()=>{const pads=DATA.board.pads;
 const a=pads.findIndex(p=>p.ref==='U1'&&p.pad==='33');
 const b=pads.findIndex(p=>p.ref==='U2'&&p.pad==='3');
 document.getElementById('fit').click();
 document.getElementById('measure').click();
 document.querySelectorAll('.pad-hit')[a].click();
 document.querySelectorAll('.pad-hit')[b].click();
 return {overlayLines:document.querySelectorAll('.measure-overlay line').length,
  text:document.getElementById('measureReadout').textContent,
  state:document.getElementById('measure').getAttribute('aria-pressed')};})()`);
check(visualMeasure.overlayLines===1&&visualMeasure.text.includes('28.2099 mm')&&visualMeasure.state==='false',
 'actual pad hit controls support complete visually inspectable measurement');
const measurePhoto=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
writeFileSync(screenshotDir+'/native-pad-measurement.png',Buffer.from(measurePhoto.data,'base64'));
for(const width of [1280,1024,820]){
 await call('Emulation.setDeviceMetricsOverride',{width,height:850,deviceScaleFactor:1,mobile:false});
 const compact=await js(`(async()=>{
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  const $=id=>document.getElementById(id);
  const title=$('canvasName'),toolbar=document.querySelector('.boardactions'),hood=$('modeKicker');
  const r=toolbar.getBoundingClientRect(),a=title.getBoundingClientRect(),b=hood.getBoundingClientRect();
  const collide=x=>x.width>0&&Math.max(x.left,r.left)<Math.min(x.right,r.right)&&
   Math.max(x.top,r.top)<Math.min(x.bottom,r.bottom);
  return {viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
   canvas:$('boardspace').clientWidth,toolbarBottom:r.bottom,intersections:[collide(a),collide(b)],
   docks:[getComputedStyle($('leftSplitter')).display,getComputedStyle($('rightSplitter')).display],
   order:{board:$('boardspace').getBoundingClientRect().top,
    inspector:$('rightSidebar').getBoundingClientRect().top,
    evidence:$('leftSidebar').getBoundingClientRect().top}};
 })()`);
 console.log('RESPONSIVE ENGINEERING WORKSPACE',width,compact);
 check(compact.viewport<=width&&compact.viewport>=width-20&&
  compact.scroll<=compact.viewport&&compact.canvas>=420&&
  compact.intersections.every(x=>!x)&&
  (width>950||(compact.docks.every(x=>x==='none')&&compact.order.board<compact.order.inspector&&
   compact.order.inspector<compact.order.evidence)),
  width+'px professional workspace has usable source canvas, non-overlapping toolbar and no overflow');
 const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 writeFileSync(screenshotDir+'/professional-'+width+'px.png',Buffer.from(shot.data,'base64'));
}
await call('Emulation.clearDeviceMetricsOverride');

ws.close();console.log('REAL NATIVE KiCad BROWSER CHECKS: ALL PASSED');
