/* 途记 1.5.1 双端界面回归（Playwright + 模拟本机桥接）
   覆盖：响应式适配、记录表盘状态机、路径库卡片、逐点审阅、桌面照片补录、设置页、非线性动效与减少动态效果。
   本脚本只验证界面层，不替代 Android 实机与真实 WebView2 桥接验收。 */
const {chromium}=require('playwright'),fs=require('fs'),path=require('path');
(async()=>{
 const base=path.resolve(__dirname,'..'),fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixture.json'),'utf8'));
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],checks=[];
 const p=await browser.newPage({viewport:{width:390,height:844}});
 p.on('pageerror',e=>errors.push('pageerror: '+e.message));
 // 底图请求在离线回归中被主动中止，其资源级报错不算界面错误
 p.on('console',m=>{if(m.type()==='error'&&!/ERR_FAILED|ERR_ABORTED|Failed to load resource/.test(m.text()))errors.push('console: '+m.text());});
 await p.route('https://tile.openstreetmap.org/**',r=>r.abort());
 await p.addInitScript(({fixture})=>{
  window.qaPlatform='android';window.qaActive=false;window.qaSingle=false;window.qaEnabled=true;window.qaStarted=Date.now()-125000;
  window.qaRoutes=[{id:1,started:fixture.points[0].t,ended:fixture.points.at(-1).t,state:'saved',count:115,mode:'track'}];
  window.qaPrefs={writeInPlace:false,defaultOffset:'+08:00',trackMode:'separate'};
  window.qaCurve=null;
  window.qaWritten=[];
  window.qaJob=null;
  window.qaPhotos={count:0,names:[],root:null};
  window.actions=[];window.qaDrop=null;
  window.demoApi=async(action,args)=>{window.actions.push(action);
   const island=()=>({enabled:window.qaEnabled,status:window.qaEnabled?'系统支持超级岛，途记尚无焦点通知权限。':'已关闭尝试，记录仍使用普通通知。'});
   if(action==='state')return {platform:window.qaPlatform,active:window.qaActive,single:window.qaSingle,started:window.qaStarted,count:window.qaActive?8:0,mode:1,routes:window.qaRoutes,island:island(),prefs:window.qaPrefs,photos:window.qaPhotos,nativeDrop:!!window.__nativeDropReady,job:window.qaJob||(window.qaWritten.length?{busy:false,ready:false,status:'完成 · 写入2张',progress:100,rows:[],points:[],tracks:[],written:window.qaWritten}:undefined)};
   if(action==='prefs'){window.qaPrefs=Object.assign({},window.qaPrefs,{[args.key]:args.value});return window.qaPrefs;}
   if(action==='import-bytes'){window.qaDrop={name:args.name,bytes:atob(args.data).length};return {id:'qa-dropped',name:args.name};}
   if(action==='import-paths')return {ids:['qa-clp'],count:((args&&args.paths)||[]).length};
   if(action==='photos-add'){
     const list=(args&&args.paths)||[];let added=0,skipped=0;
     for(const item of list){
       const name=String(item).split(/[\\/]/).pop();
       if(!/\.(nef|dng|jpe?g|png|heic|heif)$/i.test(name)){skipped++;continue;}
       if(window.qaPhotos.names.includes(name))continue;
       window.qaPhotos.names.push(name);added++;
     }
     window.qaPhotos.count=window.qaPhotos.names.length;
     window.qaPhotos.root=added?'D:\\QA':window.qaPhotos.root;
     return {added,skipped,photos:window.qaPhotos};
   }
   if(action==='photos-pick')return {cancelled:false,added:0,skipped:0,photos:window.qaPhotos};
   if(action==='photos-clear'){window.qaPhotos={count:0,names:[],root:null};return {photos:window.qaPhotos};}
   if(action==='start'||action==='single'){window.qaActive=true;window.qaSingle=action==='single';window.qaStarted=Date.now()-125000;return {};}
   if(action==='stop'){window.qaActive=false;return {};}
   if(action==='mode'){return {};}
   if(action==='island-toggle'){window.qaEnabled=args.enabled;return {};}
   if(action==='island-check')return island();
   if(action==='island-diagnose')return {eligible:false,blockedBy:'应用暂无焦点通知权限',status:'系统支持超级岛，但途记尚无焦点通知权限，使用普通通知。',gates:{switch:'on',notifications:true,protocol:3,protocolError:'',featureFlag:'true',featureFlagError:'',canShowFocus:'false',canShowFocusVia:'',canShowFocusError:'',channelImportance:'low',business:'gps_track'},device:{manufacturer:'Xiaomi',model:'QA-Device',androidSdk:35,incremental:'V816.0.4.0.UNACNXM'},last:{at:'',ok:true,error:'',payload:''}};
   if(action==='island-test')return {payload:'{"param_v2":{}}',status:'系统支持超级岛，但途记尚无焦点通知权限，使用普通通知。',blockedBy:'应用暂无焦点通知权限'};
   if(action==='island-business')return {business:(args&&args.value)||'gps_track'};
   if(action==='view')return window.qaCurve?Object.assign({},fixture,{curve:window.qaCurve}):fixture;
   if(action==='delete'){window.qaRoutes=[];return {};}
   if(action==='pick')return {path:'D:\\QA\\photos'};
   return {};
  };
 },{fixture});
 const url='file:///'+path.join(base,'shared/ui/index.html').replaceAll('\\','/');
 await p.goto(url);
 await p.waitForFunction(()=>document.body.classList.contains('android'));
 const assert=(v,s)=>{if(!v)throw Error(s);checks.push(s);};
 // 手机端固定底部导航在整页截图中会错位，故手机页取视口截图，桌面页取整页截图
 const shot=(n,full)=>p.screenshot({path:path.join(__dirname,'ui-151-'+n+'.png'),fullPage:!!full});
 // 贴着一个元素截图，避免整页截图把固定侧栏叠上来
 const shotOf=async(n,selector)=>p.locator(selector).screenshot({path:path.join(__dirname,'ui-151-'+n+'.png')});
 // 键盘模态下逐次 Tab，直到活动元素命中选择器（:focus-visible 只在键盘/脚本模态下生效）
 const focusByKeyboard=async sel=>{
  for(let i=0;i<60;i++){await p.keyboard.press('Tab');if(await p.evaluate(s=>!!document.activeElement&&document.activeElement.matches(s),sel))return true;}
  return false;
 };
 const focusedStyle=sel=>p.evaluate(s=>{
  const el=document.querySelector(s),c=getComputedStyle(el);
  return {focusVisible:el.matches(':focus-visible'),outlineColor:c.outlineColor,outlineWidth:c.outlineWidth,shadow:c.boxShadow,radius:parseFloat(c.borderRadius)||0};
 },sel);

 // 0. 焦点环与控件形态：全站圆角，不得出现直角 outline 方框
 assert(await focusByKeyboard('#record-action'),'record dial reachable by keyboard');
 const dialRing=await focusedStyle('#record-action');
 assert(dialRing.focusVisible,'keyboard focus reports :focus-visible');
 assert(/rgba\(0, 0, 0, 0\)|transparent/.test(dialRing.outlineColor),'focus outline is fully transparent (no square ring)');
 assert(dialRing.shadow!=='none','focus ring is drawn as a rounded box-shadow instead');
 const checkbox=await p.evaluate(()=>{const e=document.querySelector('#island-enabled');const c=getComputedStyle(e);return {appearance:c.appearance||c.webkitAppearance,radius:parseFloat(c.borderRadius)||0};});
 assert(checkbox.appearance==='none','checkbox drops the native square appearance');
 assert(checkbox.radius>=6,'checkbox corners are rounded');
 assert(await p.evaluate(()=>getComputedStyle(document.documentElement).webkitTapHighlightColor.replace(/\s/g,'')==='rgba(0,0,0,0)'),'android tap highlight suppressed for custom rounded feedback');

 // 1. 记录页：多宽度无横向溢出
 await p.click('nav [data-page=record]');
 for(const width of [320,360,390,412,720,1024]){
  await p.setViewportSize({width,height:844});await p.waitForTimeout(150);
  assert(!await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),`record fits ${width}px`);
 }
 // 320像素视觉证据：等入场动效播完再截图
 await p.setViewportSize({width:320,height:844});await p.waitForTimeout(1000);
 assert(await p.locator('#record-action').evaluate(e=>parseFloat(getComputedStyle(e).opacity)>0.95),'record dial fully visible at 320px');
 await shot('record-320');
 await p.setViewportSize({width:390,height:844});await p.waitForTimeout(650);
 await shot('record');
 assert(await p.locator('img[src="brand.png"]').count()===0,'no Logo images in UI');
 assert(await p.locator('.hero-sticker').isVisible(),'independent Hachiware sticker visible on plate');
 assert(await p.locator('.nav-pill').evaluate(e=>parseFloat(getComputedStyle(e).width)>10),'nav indicator follows active item');
 assert(await p.locator('.mode.selected').getAttribute('data-mode')==='1','selected mode reflects native state');
 assert(await p.locator('#elapsed').textContent()==='00:00','idle dial shows a zeroed timer before recording');

 // 2. 记录中：表盘、呼吸与非线性缓动
 await p.click('#record-action');
 await p.waitForFunction(()=>document.body.classList.contains('recording'));
 assert(/^02:0\d$/.test(await p.locator('#elapsed').textContent()),'record elapsed reflects native start');
 // 表盘秒级自走：3秒窗口内至少取到3个不同读数，仅靠3秒状态轮询做不到
 const samples=new Set();
 for(let i=0;i<11;i++){samples.add(await p.locator('#elapsed').textContent());await p.waitForTimeout(300);}
 assert(samples.size>=3,`dial timer advances every second instead of on the 3s poll (samples: ${[...samples].join(',')})`);
 assert(await p.locator('#record-action-label').textContent()==='结束并保存','active dial label switches to stop');
 assert(await p.locator('#single-action').isDisabled(),'single disabled during track');
 assert((await p.evaluate(()=>getComputedStyle(document.querySelector('.dial-pulse')).animationTimingFunction)).includes('cubic-bezier'),'nonlinear dial pulse');
 assert((await p.evaluate(()=>getComputedStyle(document.querySelector('.route-beacon')).animationTimingFunction)).includes('cubic-bezier'),'nonlinear active beacon');
 await p.waitForTimeout(500);
 await shot('recording');
 await p.click('#record-action');
 await p.waitForFunction(()=>!document.body.classList.contains('recording'));

 // 3. 单点补录
 await p.click('nav [data-page=record]');
 await p.click('#single-action');
 await p.waitForFunction(()=>document.querySelector('#record-status').textContent.includes('单点'));
 assert(await p.locator('#single-action').isDisabled(),'single mode dispatch and busy state');
 await p.click('#record-action');
 await p.waitForFunction(()=>!document.body.classList.contains('recording'));

 // 4. 设置页
 await p.click('nav [data-page=settings]');
 await p.waitForTimeout(600);
 await p.locator('#island-enabled').uncheck();
 await p.waitForFunction(()=>document.querySelector('#island-status').textContent.includes('已关闭'));
 await p.click('#island-check');
 await p.click('#island-settings');
 assert(await p.evaluate(()=>actions.includes('island-toggle')&&actions.includes('island-check')&&actions.includes('notification-settings')),'island toggle probe settings dispatch');
 // 超级岛诊断：逐条列出闸门，并明确报出卡在哪一步
 await p.click('#island-diagnose');
 await p.waitForFunction(()=>!document.querySelector('#island-extra').hidden);
 assert(await p.locator('#island-gates .gate').count()===9,'island diagnostics lists every gate');
 assert(await p.locator('#island-gates .gate.fail').count()>=1,'island diagnostics marks the blocking gate as failed');
 assert((await p.locator('#island-gates .gate.fail span').first().textContent()).includes('未授权'),'island diagnostics names the blocking reason');
 assert((await p.locator('#island-business').inputValue())==='gps_track','island diagnostics shows the saved business id');
 await p.fill('#island-business','qa_business');
 await p.click('#island-business-save');
 await p.waitForFunction(()=>actions.includes('island-business'));
 await p.click('#island-test');
 await p.waitForFunction(()=>actions.includes('island-test'));
 assert((await p.locator('#island-test-result').textContent()).includes('测试通知'),'island test reports what was sent');
 assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'settings fits phone width with diagnostics open');
 await p.evaluate(()=>document.querySelector('#notice').hidden=true);
 // 圆角控件特写证据：勾选框 / 键盘焦点环 / 超级岛诊断闸门（分三张小图，避免固定顶栏压在长元素截图上）
 await p.locator('#island-enabled').check();
 await p.locator('.island-setting .check').screenshot({path:path.join(__dirname,'ui-151-checkbox.png')});
 await p.locator('#island-gates').screenshot({path:path.join(__dirname,'ui-151-island-gates.png')});
 await focusByKeyboard('#island-check');
 await p.locator('.island-setting > .actions').screenshot({path:path.join(__dirname,'ui-151-focus-ring.png')});
 await p.evaluate(()=>document.activeElement&&document.activeElement.blur());
 await shot('settings');

 // 5. 路径库
 await p.click('nav [data-page=library]');
 await p.waitForTimeout(650);
 assert(await p.locator('.date-tile b').textContent()===String(new Date(fixture.points[0].t).getDate()),'route date tile uses real start date');
 assert((await p.locator('#stat-points').textContent())==='115','library stats sum real node count');
 await shot('library');

 // 6. 逐点审阅
 await p.getByRole('button',{name:'查看',exact:true}).click();
 await p.locator('#node-picker').selectOption('11');
 await p.waitForFunction(()=>document.querySelector('#node-number').textContent==='12 / 115');
 assert(await p.evaluate(()=>layer.getLayers().filter(x=>x instanceof L.CircleMarker&&!(x instanceof L.Circle)).length)===12,'viewer prefix includes exactly 12 nodes');
 assert(await p.locator('#node-detail .cell').count()===6,'node detail renders six measured fields');
 assert((await p.locator('#map-status').textContent()).includes('底图暂不可用'),'tile failure reported without hiding local track');

 // 6.1 手机端只有一个步骤：没有曲线时节点直连，并且界面如实说明
 assert(await p.evaluate(()=>!payload.curve),'phone payload carries no curve');
 const mobileNote=await p.locator('#curve-note').textContent();
 assert(mobileNote.includes('直线')&&mobileNote.includes('电脑端'),'phone viewer says the curve is made on the desktop');
 assert(!await p.locator('#curve-note').evaluate(e=>e.classList.contains('live')),'phone note is not marked as a live curve');
 const straight=await p.evaluate(()=>{
   const a={t:0,lat:30.0,lon:100.0},b={t:1000,lat:30.01,lon:100.1};
   const mid=curvePosition(500,a,b);
   return {lat:mid[0],lon:mid[1],linLat:(a.lat+b.lat)/2,linLon:(a.lon+b.lon)/2};
 });
 assert(Math.abs(straight.lat-straight.linLat)<1e-12&&Math.abs(straight.lon-straight.linLon)<1e-12,
   'without a curve the segment between two nodes is a straight line');

 // 6.2 电脑端按节点重建曲线，界面标明来源，求值与 Python 一致
 await p.evaluate(()=>{window.qaCurve={version:'pchip-4d-v2',
   times:[0,1000,4000],
   values:[[30.0,30.001,30.004],[179.998,179.99900000000002,180.002],[10.0,12.0,20.0]],
   slopes:[[1.0000000000015183e-06,1.0000000000007286e-06,9.999999999991495e-07],
           [1.0000000000426707e-06,1.0000000000174067e-06,9.999999999668795e-07],
           [0.0018333333333333335,0.0022325581395348836,0.0031666666666666666]]};});
 await p.evaluate(async()=>{await openRoute(1);});
 await p.waitForFunction(()=>!!(payload&&payload.curve));
 assert(await p.locator('#curve-note').evaluate(e=>e.classList.contains('live')),'desktop note is marked as a live curve');
 assert((await p.locator('#curve-note').textContent()).includes('电脑端'),'desktop viewer says who built the curve');
 // 期望值由 Python curve.evaluate() 独立算出，这里只比数值，比的是两份实现的求值一致性
 const parity=await p.evaluate(()=>{
   const a={t:0,lat:30.0,lon:179.998},b={t:1000,lat:30.001,lon:179.999};
   return [500,2500,3999].map(t=>curvePosition(t,a,b));
 });
 const expectedLat=[30.0005,30.002500000000005,30.003999];
 const expectedLon=[179.99850000000004,-179.9995,-179.99800100000004];
 const wrap=d=>Math.abs(((d%360)+540)%360-180);
 parity.forEach((got,i)=>{
   assert(Math.abs(got[0]-expectedLat[i])<1e-9,`curve parity latitude ${i}: ${got[0]} vs ${expectedLat[i]}`);
   assert(wrap(got[1]-expectedLon[i])<1e-9,`curve parity longitude ${i}: ${got[1]} vs ${expectedLon[i]}`);
 });
 await p.evaluate(()=>{window.qaCurve=null;payload=null;});

 // 轨迹提示气泡默认是直角小方块加方形箭头，必须已改为圆角胶囊
 await p.evaluate(()=>{const m=layer.getLayers().find(x=>x.openTooltip);if(m)m.openTooltip();});
 await p.waitForTimeout(300);
 const tooltip=await p.evaluate(()=>{const el=document.querySelector('.leaflet-tooltip');if(!el)return null;const c=getComputedStyle(el);return {radius:parseFloat(c.borderRadius)||0,arrow:getComputedStyle(el,'::before').display};});
 assert(tooltip&&tooltip.radius>=10,'map tooltip uses rounded corners');
 assert(tooltip.arrow==='none','map tooltip square arrow removed');
 await p.waitForTimeout(600);
 await shot('viewer');
 // 宽视口下的回看页（桌面端同一份 DOM）
 await p.setViewportSize({width:1180,height:860});await p.waitForTimeout(500);
 assert(!await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'viewer fits desktop width');
 await shot('viewer-wide',true);
 await p.setViewportSize({width:390,height:844});await p.waitForTimeout(200);

 // 7. 桌面端：路径库 -> 照片补录 -> 设置
 await p.click('#back-library');
 await p.setViewportSize({width:1180,height:860});
 await p.evaluate(async()=>{qaPlatform='windows';await refresh();switchPage('photos');});
 assert(await p.locator('nav [data-page=settings]').isVisible(),'Windows exposes the settings entry');
 assert(!await p.locator('nav [data-page=record]').isVisible(),'Windows hides phone recording');

 // 7.1 轨迹多选：勾选状态、步进器与择优提示
 assert(await p.locator('#track-picker input[data-track]').count()===1,'track picker lists every saved route');
 assert((await p.locator('#track-count').textContent())==='未选择','track counter starts empty');
 assert(await p.locator('#steps li.active b').textContent()==='01','stepper starts at track selection');
 await p.locator('#track-picker .track-item').first().click();
 assert((await p.locator('#track-count').textContent())==='已选 1 条','picking a track updates the counter');
 assert(await p.locator('#track-picker .track-item').first().evaluate(e=>e.classList.contains('picked')),'picked track is highlighted');
 assert(await p.locator('#steps li.active b').textContent()==='02','stepper moves on to photo import');
 await p.locator('#tracks-none').click();
 assert(await p.locator('#steps li.active b').textContent()==='01','clearing tracks returns to step one');
 await p.locator('#tracks-all').click();
 assert((await p.locator('#track-count').textContent())==='已选 1 条','select-all picks every track');

 // 7.2 导入照片：拖入的 NEF 进入待处理照片集，目录方式仍可用
 assert((await p.locator('#photo-count').textContent())==='尚未导入','photo list starts empty');
 // 7.2.1 曲线生成方式：默认各自成曲线，可切到合并并持久化
 assert(await p.locator('#track-mode .seg[data-tracks=separate]').getAttribute('aria-checked')==='true','track mode defaults to one curve per track');
 assert((await p.locator('#track-mode-note').textContent()).includes('各自'),'separate mode explains itself');
 await p.locator('#track-mode .seg[data-tracks=merge]').click();
 await p.waitForFunction(()=>qaPrefs.trackMode==='merge');
 assert(await p.locator('#track-mode .seg[data-tracks=merge]').getAttribute('aria-checked')==='true','merge mode is selectable');
 assert((await p.locator('#track-mode-note').textContent()).includes('单点补录不参与合并'),'merge mode states the single-point rule');
 assert((await p.locator('#track-mode-note').textContent()).includes('120 秒'),'merge mode states the long-gap rule');
 const mergeArgs=await p.evaluate(()=>options());
 assert(mergeArgs.mergeTracks===true,'merge choice reaches the native options');
 await p.locator('#track-mode .seg[data-tracks=separate]').click();
 await p.waitForFunction(()=>qaPrefs.trackMode==='separate');
 assert((await p.evaluate(()=>options())).mergeTracks===false,'separate choice reaches the native options');

 // 7.2.2 布局：匹配位置面板与处理进度面板同宽同列，写入按钮在匹配位置面板内的地图下方
 const layout=await p.evaluate(()=>{
   const grid=document.querySelector('.photo-grid');
   const side=grid.querySelector(':scope > .photo-side');
   const panels=side?[...side.children].filter(e=>e.classList.contains('panel')):[];
   const progress=panels[0].getBoundingClientRect();
   const mapPanel=document.querySelector('#photo-map-panel');
   const map=mapPanel.getBoundingClientRect();
   const write=document.querySelector('#write').getBoundingClientRect();
   const canvas=document.querySelector('#photo-map').getBoundingClientRect();
   const preview=document.querySelector('#preview').getBoundingClientRect();
   return {
     gridChildren:grid.children.length,
     hasSide:!!side,
     sidePanels:panels.length,
     firstPanelIsProgress:panels[0]===document.querySelector('#photo-rows').closest('.panel'),
     mapIsSecondPanel:panels[1]===mapPanel,
     sameLeft:Math.abs(progress.left-map.left)<1.5,
     sameWidth:Math.abs(progress.width-map.width)<1.5,
     mapBelowProgress:map.top>=progress.bottom-1,
     progressHugsContent:progress.height<map.top-progress.top,
     writeInsideMapPanel:!!document.querySelector('#photo-map-panel #write'),
     writeBelowCanvas:write.top>=canvas.bottom-1,
     previewOutsideMapPanel:!document.querySelector('#photo-map-panel #preview'),
     previewInForm:!!document.querySelector('.photo-grid > .panel #preview'),
   };
 });
 assert(layout.gridChildren===2&&layout.hasSide,'the grid holds the form and one right-hand stack');
 assert(layout.sidePanels===2&&layout.firstPanelIsProgress&&layout.mapIsSecondPanel,
   'the right column stacks the progress panel then the map panel');
 assert(layout.sameLeft&&layout.sameWidth,'the map panel is exactly as wide as the progress panel');
 assert(layout.mapBelowProgress,'the map panel sits below the progress panel in one column');
 assert(layout.progressHugsContent,'the progress panel is not stretched to the height of the form');
 assert(layout.writeInsideMapPanel&&layout.writeBelowCanvas,'the write button lives under the map inside the map panel');
 assert(layout.previewOutsideMapPanel&&layout.previewInForm,'the preview button stays in the left form');
 assert(await p.locator('#preview').evaluate(e=>e.closest('.actions').classList.contains('stacked')),'the form action group uses the stacked layout');
 // 电脑端没有预览结果时也要常显，并给出占位提示
 assert(!await p.locator('#photo-map-panel').evaluate(e=>e.hidden),'desktop keeps the map panel visible before any preview');
 assert(!await p.locator('#photo-map-empty').evaluate(e=>e.hidden),'the empty placeholder is shown before a preview');
 assert(await p.evaluate(()=>!photoMap),'no map instance is created before there is anything to show');
 await p.evaluate(()=>window.nativeDropReady(true));
 await p.evaluate(()=>window.nativeDropFiles(['D:\\QA\\b.nef','D:\\QA\\a.nef','D:\\QA\\track.clp']));
 await p.waitForFunction(()=>!!window.qaPhotos&&qaPhotos.count===2);
 assert(await p.evaluate(()=>actions.includes('photos-add')),'dropped NEF reaches the photo bridge');
 assert(await p.evaluate(()=>actions.includes('import-paths')),'dropped .clp and .nef are split by type');
 await p.waitForFunction(()=>document.querySelectorAll('#photo-list .photo-row').length===2);
 assert((await p.locator('#photo-count').textContent())==='已导入 2 张','imported photo count is shown');
 assert(await p.evaluate(()=>document.querySelector('#photo-list').classList.contains('ready')),'photo list switches to the ready style');
 assert(await p.locator('#steps li.active b').textContent()==='03','stepper advances once tracks and photos are ready');
 assert((await p.locator('#photo-source-note').textContent()).includes('优先'),'the page states that imported files outrank the folder');
 await p.locator('#photos-clear').click();
 await p.waitForFunction(()=>qaPhotos.count===0);
 assert((await p.locator('#photo-count').textContent())==='尚未导入','clearing photos empties the list');
 await p.evaluate(()=>window.nativeDropFiles(['D:\\QA\\a.nef']));
 await p.waitForFunction(()=>qaPhotos.count===1);

 // 7.2.1b 多格式：DNG/JPG/PNG/HEIC 与 NEF 一样按照片导入，不支持的扩展名被跳过
 await p.evaluate(()=>window.nativeDropFiles(['D:\\QA\\p.dng','D:\\QA\\p.jpg','D:\\QA\\p.png','D:\\QA\\p.heic','D:\\QA\\p.heif','D:\\QA\\p.tif','D:\\QA\\p.bmp']));
 await p.waitForFunction(()=>qaPhotos.names.includes('p.heif'));
 const multi=await p.evaluate(()=>qaPhotos.names.slice().sort());
 assert(['a.nef','p.dng','p.heic','p.heif','p.jpg','p.png'].every(n=>multi.includes(n)),'supported photo formats are all accepted: '+multi.join(','));
 assert(!multi.includes('p.tif')&&!multi.includes('p.bmp'),'unsupported formats are skipped: '+multi.join(','));
 await p.evaluate(async()=>{await api('photos-clear');await refresh();});
 await p.evaluate(()=>window.nativeDropFiles(['D:\\QA\\a.nef']));
 await p.waitForFunction(()=>qaPhotos.count===1);

 await p.locator('[data-pick=photos]').click();
 await p.waitForFunction(()=>document.querySelector('#photos-path').value.length>0);
 assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'photos page fits desktop width');
 assert(await p.locator('#photo-rows').evaluate(el=>el.closest('table').querySelectorAll('thead th').length)===5,'photo table lists number, photo, track, result and coordinates');

 // 7.3 预览结果：照片编号 + 地图图钉 + 行与图钉双向联动
 await p.evaluate(()=>{qaJob={busy:false,ready:true,status:'预览完成 · 4张照片 · 1条曲线 · 2张可写入副本',progress:100,inPlace:false,
   rows:[['1','a.nef','9/24 13:55 · 115点','可写入副本 · 曲线插值（前后间隔 14 秒）','—'],
         ['2','b.nef','9/24 13:55 · 115点','可写入副本 · 曲线插值（前后间隔 30 秒）','—'],
         ['3','c.nef','9/24 13:55 · 115点','照片已有经纬度或海拔，未勾选覆盖，保留原件','—'],
         ['4','d.nef','9/24 13:55 · 115点','所选轨迹的时间范围都未覆盖曝光时刻','—']],
   points:[{n:1,relative:'a.nef',lat:1.1800000,lon:2.1100000,alt:1513.0,method:'interpolated',track:'9/24 13:55 · 115点'},
           {n:2,relative:'b.nef',lat:1.2100000,lon:2.1400000,alt:1516.5,method:'interpolated',track:'9/24 13:55 · 115点'}],
   tracks:[{label:'9/24 13:55 · 115点',points:[[1.1700000,2.1000000],[1.2000000,2.1300000],[1.2100000,2.1400000],[1.2200000,2.1500000]]}],
   written:[]};});
 await p.evaluate(async()=>{await refresh();});
 await p.waitForFunction(()=>!document.querySelector('#photo-map-panel').hidden);
 assert(await p.locator('#photo-rows tr').count()===4,'preview lists every photo');
 const firstRow=await p.locator('#photo-rows tr').first().locator('td').allTextContents();
 assert(firstRow[0]==='1','the preview table numbers photos from one');
 assert(firstRow[1]==='a.nef','the number column precedes the file name');
 assert(await p.evaluate(()=>document.querySelector('#photo-rows tr').dataset.n)==='1','the row carries its number');
 assert((await p.locator('#photo-map-summary').textContent())==='2 张 · 1 条曲线','map summary counts pins and curves');
 await p.waitForFunction(()=>document.querySelectorAll('.photo-pin').length===2);
 const pinText=await p.evaluate(()=>[...document.querySelectorAll('.photo-pin')].map(e=>e.textContent.trim()));
 assert(pinText.join(',')==='1,2','the map shows one numbered pin per matched photo');
 // 点表格行 -> 对应图钉被选中
 await p.locator('#photo-rows tr').nth(1).click();
 await p.waitForFunction(()=>!!document.querySelector('.photo-pin.picked'));
 assert((await p.locator('.photo-pin.picked').textContent()).trim()==='2','clicking a row highlights its pin');
 assert(await p.locator('#photo-rows tr').nth(1).evaluate(e=>e.classList.contains('picked')),'the clicked row is highlighted');
 // 点图钉 -> 对应行被选中，且旧高亮被清掉
 await p.locator('.photo-pin').first().click();
 await p.waitForFunction(()=>document.querySelector('.photo-pin.picked')?.textContent.trim()==='1');
 assert(await p.locator('#photo-rows tr').first().evaluate(e=>e.classList.contains('picked')),'clicking a pin highlights its row');
 assert(await p.locator('#photo-rows tr.picked').count()===1,'only one row stays highlighted');
 assert(await p.locator('.photo-pin.picked').count()===1,'only one pin stays highlighted');
 await p.evaluate(()=>document.querySelector('#notice').hidden=true);
 await p.waitForTimeout(700);
 await shot('windows-pins',true);
 await p.evaluate(()=>{const el=document.querySelector('#photo-map-panel');el.scrollIntoView({block:'center'});});
 await p.waitForTimeout(500);
 await shotOf('windows-map','#photo-map-panel');
 // 一张都没匹配上时地图仍在（只有轨迹），便于判断为什么没匹配
 await p.evaluate(()=>{qaJob=Object.assign({},qaJob,{points:[]});});
 await p.evaluate(async()=>{await refresh();});
 await p.waitForFunction(()=>document.querySelectorAll('.photo-pin').length===0);
 assert(!await p.locator('#photo-map-panel').evaluate(e=>e.hidden),'the map stays when only tracks are left');
 // 手机端不得出现地图面板
 await p.evaluate(async()=>{qaPlatform='android';qaJob=null;await refresh();});
 assert(await p.locator('#photo-map-panel').evaluate(e=>e.hidden),'the phone never shows the pin map');
 await p.evaluate(async()=>{qaPlatform='windows';await refresh();});

 // 7.4 写入结果预览：只渲染真实回传的经纬度与海拔，并带上编号与所用轨迹
 await p.evaluate(()=>{qaWritten=[{n:1,relative:'a.nef',track:'9/24 13:55 · 115点',lat:1.1900000,lon:2.1200000,alt:1513.04,method:'interpolated',captureUtc:'2026-09-24T05:55:08Z'},{n:2,relative:'b.nef',track:'单点补录',lat:1.2300000,lon:2.1600000,alt:null,method:'single',captureUtc:'2026-09-24T05:56:08Z'}];});
 await p.evaluate(async()=>{await refresh();});
 await p.waitForFunction(()=>!document.querySelector('#written-panel').hidden);
 assert(await p.locator('#written-rows tr').count()===2,'written preview lists every written photo');
 const firstWritten=await p.locator('#written-rows tr').first().locator('td').allTextContents();
 assert(firstWritten[0]==='1','written preview keeps the photo number');
 assert(firstWritten[2]==='9/24 13:55 · 115点','written preview names the track that was used');
 assert(firstWritten[3]==='1.1900000'&&firstWritten[4]==='2.1200000','written preview shows the exact written coordinates');
 assert(firstWritten[5]==='1513.0 米','written preview shows the written altitude');
 const secondWritten=await p.locator('#written-rows tr').nth(1).locator('td').allTextContents();
 assert(secondWritten[0]==='2','every written row keeps its number');
 assert(secondWritten[5]==='未知','missing altitude is shown as unknown, never zero');
 await p.evaluate(()=>document.querySelector('#notice').hidden=true);
 await p.waitForTimeout(600);
 await shot('windows-photos',true);

 // 8. 拖入：有原生路径时由桌面端驱动，没有时才退回字节通道
 await p.evaluate(()=>window.nativeDropReady(false));
 await p.evaluate(()=>{
   const dt=new DataTransfer();
   dt.items.add(new File([new Uint8Array([67,76,80,49,1,2,3,4])],'dropped.clp'));
   window.dispatchEvent(new DragEvent('dragenter',{dataTransfer:dt,bubbles:true}));
 });
 assert(!await p.locator('#dropzone').evaluate(e=>e.hidden),'dragging a file over the window shows the drop overlay');
 assert((await p.locator('#dropzone-hint').textContent()).includes('.nef'),'drop overlay explains both drop types');
 await p.evaluate(()=>{
   const dt=new DataTransfer();
   dt.items.add(new File([new Uint8Array([67,76,80,49,1,2,3,4])],'dropped.clp'));
   window.dispatchEvent(new DragEvent('dragover',{dataTransfer:dt,bubbles:true}));
   window.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}));
 });
 await p.waitForFunction(()=>!!window.qaDrop);
 const dropped=await p.evaluate(()=>window.qaDrop);
 assert(dropped.name==='dropped.clp'&&dropped.bytes===8,'without native paths a dropped .clp uses the byte bridge');
 assert(await p.locator('#dropzone').evaluate(e=>e.hidden),'drop overlay closes after the drop');
 await p.evaluate(()=>{
   const dt=new DataTransfer();
   dt.items.add(new File([new Uint8Array([1,2,3])],'notes.txt'));
   window.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}));
 });
 await p.waitForFunction(()=>document.querySelector('#notice').textContent.includes('没有 .clp'));
 assert((await p.locator('#notice').textContent()).includes('没有 .clp'),'non-clp drops are rejected with a clear message');
 // 原生路径可用后，界面不再经手字节流
 await p.evaluate(()=>{window.qaDrop=null;window.nativeDropReady(true);});
 await p.evaluate(()=>{
   const dt=new DataTransfer();
   dt.items.add(new File([new Uint8Array([67,76,80,49,9,9,9,9])],'again.clp'));
   window.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}));
 });
 await p.waitForTimeout(400);
 assert(await p.evaluate(()=>window.qaDrop===null),'with native paths the page stops handling drops itself');
 await p.evaluate(()=>document.querySelector('#notice').hidden=true);

 // 桌面端设置：写入方式切换 + 覆盖确认 + 默认时区
 await p.evaluate(()=>switchPage('settings'));
 await p.waitForTimeout(500);
 assert(await p.locator('#settings .setting.desktop').count()===2,'desktop settings shows only its own two cards');
 assert(!await p.locator('#settings .setting.mobile-only').first().isVisible(),'desktop settings hides phone-only cards');
 assert(await p.locator('#write-mode .seg[data-mode=copy]').getAttribute('aria-checked')==='true','write mode defaults to copy');
 assert((await p.locator('#write').textContent())==='写入照片副本','copy mode labels the write button accordingly');
 await p.locator('#write-mode .seg[data-mode=inplace]').click();
 await p.waitForFunction(()=>document.querySelector('#confirm-mode').open);
 assert(await p.locator('#confirm-mode').isVisible(),'switching to overwrite-original asks for confirmation first');
 await p.click('#accept-inplace');
 await p.waitForFunction(()=>document.querySelector('#write-mode .seg[data-mode=inplace]').getAttribute('aria-checked')==='true');
 assert(await p.evaluate(()=>window.qaPrefs.writeInPlace===true),'overwrite mode is persisted through the prefs bridge');
 assert((await p.locator('#write').textContent())==='覆盖原始照片','overwrite mode relabels the write button');
 assert((await p.locator('#output-label').textContent()).includes('备份'),'overwrite mode turns the output field into an optional backup folder');
 assert(await p.locator('#mode-hint').evaluate(e=>e.classList.contains('warn')),'overwrite mode shows a warning hint');
 await p.fill('#default-offset','+09:00');
 await p.click('#default-offset-save');
 await p.waitForFunction(()=>window.qaPrefs.defaultOffset==='+09:00');
 assert((await p.locator('#offset').inputValue())==='+09:00','saved default timezone prefills the capture form');
 await p.evaluate(()=>document.querySelector('#notice').hidden=true);
 await p.waitForTimeout(500);
 await shot('windows-settings',true);

 await p.evaluate(()=>switchPage('library'));
 await p.waitForTimeout(600);
 await shot('windows-library',true);
 // 平板宽度下的两栏记录页
 await p.evaluate(async()=>{qaPlatform='android';await refresh();switchPage('record');});
 await p.setViewportSize({width:1024,height:820});await p.waitForTimeout(700);
 assert(await p.evaluate(()=>getComputedStyle(document.querySelector('.hero')).gridTemplateColumns.split(' ').length===2),'wide record page uses two columns');
 await shot('record-tablet',true);

 // 8. 空状态
 await p.setViewportSize({width:390,height:844});
 await p.evaluate(async()=>{qaPlatform='android';await refresh();switchPage('library');});
 await p.getByRole('button',{name:'删除',exact:true}).click();
 await p.click('#delete-route');
 assert(await p.locator('#empty').isVisible(),'deleted route produces empty state');

 // 9. 减少动态效果
 await p.emulateMedia({reducedMotion:'reduce'});
 assert(await p.evaluate(()=>getComputedStyle(document.querySelector('.page:not([hidden])')).animationName)==='none','reduced motion disables page animation');
 assert(await p.evaluate(()=>getComputedStyle(document.querySelector('.hero-art .journey-line')).animationName)==='none','reduced motion disables track draw-in');
 assert(errors.length===0,'no JavaScript errors: '+errors.join(' | '));
 fs.writeFileSync(path.join(__dirname,'ui-151-verification.json'),JSON.stringify({ok:true,checks,errors},null,2));
 console.log(JSON.stringify({ok:true,count:checks.length,checks,errors},null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
