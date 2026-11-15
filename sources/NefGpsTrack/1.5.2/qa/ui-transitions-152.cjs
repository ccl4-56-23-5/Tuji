/* Browser-only regression using synthetic coordinates and a simulated native bridge.
   NODE_PATH must resolve the installed Playwright package; no device claims. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..');
const out=process.env.TUJI_UI_QA_OUTPUT||path.resolve(root,'../../..','output/途记/1.5.2/qa-ui');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixture.json'),'utf8'));
fs.mkdirSync(out,{recursive:true});
const checks=[],errors=[];
const check=(value,label)=>{assert.ok(value,label);checks.push(label);};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const p=await browser.newPage({viewport:{width:390,height:844}});
  p.on('pageerror',e=>errors.push(e.message));
  await p.route('https://tile.openstreetmap.org/**',r=>r.abort());
  await p.addInitScript(({fixture})=>{
   window.qaViewDelay=0;window.qaPlatform='android';
   window.demoApi=async(action,args)=>{
    if(action==='state')return {platform:window.qaPlatform,active:false,count:0,mode:0,prefs:{},routes:[{id:1,started:fixture.points[0].t,ended:fixture.points.at(-1).t,state:'saved',count:fixture.points.length,mode:'track'}],island:{status:'QA 模拟',enabled:true}};
    if(action==='view'){await new Promise(r=>setTimeout(r,window.qaViewDelay));return fixture;}
    if(action==='island-diagnose')return {status:'QA 模拟诊断',gates:{switch:'on',notifications:true,protocol:3,featureFlag:'true',canShowFocus:'false',channelImportance:'low'},device:{model:'Synthetic'}};
    return {};
   };
  },{fixture});
  await p.goto('file:///'+path.join(root,'shared/ui/index.html').replaceAll('\\','/'));
  await p.waitForFunction(()=>document.body.classList.contains('android'));
  const settled=async(name)=>{await p.waitForFunction(name=>document.querySelector('#'+name)?.getAttribute('aria-hidden')==='false'&&document.querySelectorAll('.page:not([hidden])').length===1&&[...document.querySelectorAll('.page')].every(e=>!e.getAnimations().length),name);};
  const go=async name=>{await p.evaluate(n=>switchPage(n),name);await settled(name);};
  const pose=el=>{const c=getComputedStyle(el),m=new DOMMatrixReadOnly(c.transform);return {opacity:+c.opacity,x:m.m41,y:m.m42};};
  await settled('record');
  for(const width of [320,360,390,412,720,1024]){
   await p.setViewportSize({width,height:844});
   for(const name of ['library','settings','record']){
    await go(name);
    check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${name} fits ${width}px`);
   }
  }
  await p.setViewportSize({width:390,height:844});
  await go('record');
  await p.evaluate(()=>document.querySelector('#record').scrollTop=180);
  const scroll=await p.locator('#record').evaluate(e=>e.scrollTop);
  await go('settings');await go('record');
  check(Math.abs(await p.locator('#record').evaluate(e=>e.scrollTop)-scroll)<1,'Each mobile page preserves its own scroll position');
  await p.locator('#record').evaluate(e=>e.scrollTop=0);
  const reversal=await p.evaluate(async()=>{
   const pose=id=>{const c=getComputedStyle(document.querySelector('#'+id)),m=new DOMMatrixReadOnly(c.transform);return {opacity:+c.opacity,x:m.m41};};
   switchPage('library');await new Promise(r=>setTimeout(r,90));
   const before=[pose('record'),pose('library')];switchPage('record');
   return {before,after:[pose('record'),pose('library')],easing:document.querySelector('#record').getAnimations()[0]?.effect.getTiming().easing};
  });
  for(let i=0;i<2;i++){check(Math.abs(reversal.before[i].x-reversal.after[i].x)<.05&&Math.abs(reversal.before[i].opacity-reversal.after[i].opacity)<.005,`Interrupted reversal retains page ${i} position and opacity`);}
  check(reversal.easing.startsWith('cubic-bezier'),'Page motion uses nonlinear easing');
  await settled('record');
  await p.evaluate(async()=>{for(const name of ['library','settings','record','settings','library']){switchPage(name);await new Promise(r=>setTimeout(r,35));}});
  await settled('library');
  check(await p.evaluate(()=>[...document.querySelectorAll('.page')].filter(e=>!e.hidden).map(e=>e.id).join()==='library'),'Rapid three-way navigation settles on the latest target');
  check(await p.evaluate(()=>[...document.querySelectorAll('.page')].every(e=>e.inert===(e.id!=='library'))),'Exiting and hidden pages cannot receive input');
  await p.evaluate(()=>openRoute(1));await settled('viewer');
  check(await p.locator('#map').evaluate(e=>e.clientWidth>0&&e.clientHeight>0),'Viewer map has a usable size after entry');
  await p.evaluate(()=>handleNativeBack());await settled('library');
  check(await p.locator('#heading').textContent()==='我的路径','Native back returns viewer to library');
  await p.evaluate(()=>{qaViewDelay=180;openRoute(1);switchPage('settings');});
  await settled('settings');await p.waitForTimeout(220);
  check(await p.locator('#viewer').isHidden(),'A delayed route response cannot reopen a page after navigating away');
  await p.evaluate(()=>{qaViewDelay=160;openRoute(1);handleNativeBack();});
  await p.waitForTimeout(200);
  check(await p.locator('#settings').getAttribute('aria-hidden')==='false','Back cancels a pending route load');
  await p.locator('#island-diagnose').click();
  await p.waitForFunction(()=>document.querySelector('#island-diagnose').getAttribute('aria-expanded')==='true');
  await p.waitForTimeout(70);
  await p.evaluate(()=>handleNativeBack());
  await p.waitForFunction(()=>document.querySelector('#island-extra').hidden);
  check(await p.locator('#settings').getAttribute('aria-hidden')==='false','Back closes expanded diagnostics before leaving settings');
  const disclosure=await p.evaluate(async()=>{
   setDiagnostics(true);await new Promise(r=>setTimeout(r,90));
   const e=document.querySelector('#island-extra'),before=e.getBoundingClientRect().height;
   setDiagnostics(false);const after=e.getBoundingClientRect().height;
   const motion=e.getAnimations()[0];motion.pause();motion.currentTime=299;
   return {before,after,endHeight:e.getBoundingClientRect().height,endMargin:parseFloat(getComputedStyle(e).marginTop)};
  });
  check(Math.abs(disclosure.before-disclosure.after)<.05,'Diagnostic collapse reverses from its currently displayed height');
  check(disclosure.endHeight<1.1&&disclosure.endMargin<1,`Diagnostic padding, border and margin collapse before hiding without a final jump: ${JSON.stringify(disclosure)}`);
  await p.evaluate(()=>document.querySelector('#island-extra').getAnimations()[0].finish());
  await p.waitForFunction(()=>document.querySelector('#island-extra').hidden);
  await p.evaluate(()=>handleNativeBack());await settled('record');
  check(await p.evaluate(()=>handleNativeBack())===false,'Back at record root delegates to Android');
  await go('library');
  const dialogReversal=await p.evaluate(async()=>{
   confirmDelete(1);await new Promise(r=>setTimeout(r,80));closeDialog(document.querySelector('#confirm'));
   await new Promise(r=>setTimeout(r,60));
   const e=document.querySelector('#confirm'),c=getComputedStyle(e),before={opacity:+c.opacity,transform:c.transform};
   confirmDelete(1);const d=getComputedStyle(e);return {before,after:{opacity:+d.opacity,transform:d.transform}};
  });
  check(Math.abs(dialogReversal.before.opacity-dialogReversal.after.opacity)<.005&&dialogReversal.before.transform===dialogReversal.after.transform,'Dialog reopening continues from its closing position');
  await p.waitForTimeout(380);
  check(await p.locator('#confirm').evaluate(e=>e.open&&!e.inert),'Old dialog close callbacks cannot close a reopened dialog');
  await p.keyboard.press('Escape');
  await p.waitForFunction(()=>!document.querySelector('#confirm').open);
  check(await p.locator('#library').getAttribute('aria-hidden')==='false','Escape dismisses dialog without leaving the underlying page');
  await p.evaluate(()=>showNativeNotice('已导出','已保存合成测试路径'));
  await p.waitForTimeout(350);
  await p.screenshot({path:path.join(out,'notice-dialog-390.png')});
  await p.evaluate(()=>handleNativeBack());await p.waitForFunction(()=>!document.querySelector('#native-notice').open);
  await p.evaluate(()=>toast('已保存合成测试路径'));await p.waitForTimeout(360);
  check(await p.locator('#notice').evaluate(e=>Math.abs(e.getBoundingClientRect().left+e.getBoundingClientRect().width/2-innerWidth/2)<1),'Animated toast remains horizontally centered');
  await p.evaluate(()=>{renderDetail({t:1,lat:1,lon:1,alt:20,altSource:'interpolated-msl',altAccuracy:null});});
  check((await p.locator('#node-detail').textContent()).includes('20.0 米（估算）'),'Interpolated altitude is explicitly labelled as estimated');
  await p.evaluate(()=>renderDetail({t:1,lat:1,lon:1,alt:null,ellipsoidAlt:20}));
  check((await p.locator('#node-detail').textContent()).includes('海拔未知')&&(await p.locator('#node-detail').textContent()).includes('椭球高（非海拔）20.0 米'),'Ellipsoid height is displayed separately from unknown MSL altitude');
  await go('settings');await p.screenshot({path:path.join(out,'settings-390.png')});
  await p.emulateMedia({reducedMotion:'reduce'});
  await p.evaluate(()=>{switchPage('record');switchPage('library');showDialog(document.querySelector('#confirm'));closeDialog(document.querySelector('#confirm'));});
  await settled('library');
  check(await p.locator('#confirm').evaluate(e=>!e.open),'Reduced motion performs immediate dialog completion');
  check(await p.evaluate(()=>motions.size===0),'Reduced motion leaves no pending JavaScript animations');
  await p.emulateMedia({reducedMotion:'no-preference'});
  await p.evaluate(()=>switchPage('settings'));await p.waitForTimeout(60);
  await p.emulateMedia({reducedMotion:'reduce'});await settled('settings');
  check(await p.evaluate(()=>motions.size===0),'Enabling reduced motion during a transition settles its target immediately');
  await p.emulateMedia({reducedMotion:'no-preference'});
  await p.evaluate(()=>{qaPlatform='windows';return refresh();});
  await p.setViewportSize({width:1280,height:900});await p.evaluate(()=>switchPage('photos'));await p.waitForTimeout(750);
  check(await p.locator('#photos').isVisible(),'Desktop photo page remains available');
  check(await p.evaluate(()=>getComputedStyle(document.querySelector('.page-stage')).position==='static'),'Desktop retains the original document layout');
  await p.screenshot({path:path.join(out,'windows-photos-1280.png'),fullPage:true});
  check(errors.length===0,'No JavaScript page errors');
  fs.writeFileSync(path.join(out,'ui-transitions-152.json'),JSON.stringify({passed:true,environment:'Headless Microsoft Edge / Playwright; simulated native bridge, synthetic route; no Android device attached',checks,errors,reversal,dialogReversal},null,2));
  console.log(JSON.stringify({passed:true,checks:checks.length,out}));
 }finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(path.join(out,'ui-transitions-152.json'),JSON.stringify({passed:false,checks,errors,error:e.stack},null,2));console.error(e);process.exitCode=1;});
