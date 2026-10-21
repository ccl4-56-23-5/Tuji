/* 途记 1.5.1 双端界面脚本
   桥接契约：Android 走 window.Native + window.nativeReply，桌面走 pywebview.api.request，QA 走 window.demoApi。
   本文件与 index.html、style.css 一起由构建脚本同步到 Android assets 并嵌入 Windows EXE。 */
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let sequence=0,pending=new Map(),state={},prefs={},page='record',routeId=null,payload=null,node=0,map,layer,tileLayer,lastRoutes='',jobKey='',writtenKey='',pointsKey='',photoMap=null,photoLayers=null,photoMarkers=null,pickedSpot=null,photoMapShown=false,prefsKey='',photosKey='';
const WEEK=['日','一','二','三','四','五','六'];
// 标题按平台取词：手机端讲记录，电脑端讲写入，避免出现与当前页面无关的说法。
const HEADINGS={
  android:{record:'记录沿途',library:'我的路径',photos:'照片补录',settings:'记录偏好',viewer:'沿途回看'},
  windows:{record:'记录沿途',library:'我的路径',photos:'照片补录',settings:'写入偏好',viewer:'沿途回看'}
};

/* ---------- 桥接 ---------- */
window.nativeReply=(token,data,error)=>{const p=pending.get(token);if(p){pending.delete(token);clearTimeout(p.timer);error?p.reject(Error(error)):p.resolve(data);}};
async function api(action,args={}){
  if(window.Native)return new Promise((resolve,reject)=>{
    const id=String(++sequence),timer=setTimeout(()=>{pending.delete(id);reject(Error('操作超时，请重试'));},120000);
    pending.set(id,{resolve,reject,timer});Native.request(id,action,JSON.stringify(args));
  });
  if(window.pywebview){const r=await pywebview.api.request(action,args);if(r.error)throw Error(r.error);return r;}
  if(window.demoApi)return window.demoApi(action,args);
  throw Error('本机服务尚未就绪');
}

/* ---------- 提示 ---------- */
let toastTimer;
function toast(text){
  const el=$('#notice');
  el.textContent=text;el.hidden=false;
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>{el.hidden=true;},5500);
}
async function attempt(fn){try{return await fn();}catch(e){toast(e.message||String(e));}}

/* ---------- 格式化 ---------- */
function clock(t){return t?new Date(t).toLocaleTimeString('zh-CN',{hour12:false}):'—';}
function date(t){return new Date(t).toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'});}
function shortDate(t){const d=new Date(t);return `${d.getMonth()+1}/${d.getDate()}`;}
function dayLabel(t){const d=new Date(t);return `${d.getMonth()+1}月${d.getDate()}日 · 周${WEEK[d.getDay()]}`;}
function pad(n){return String(n).padStart(2,'0');}
function elapsedText(seconds){return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].filter((_,i)=>i>0||seconds>=3600).map(pad).join(':');}
function durationText(ms){
  if(!ms||ms<0)return '';
  const total=Math.round(ms/1000),h=Math.floor(total/3600),m=Math.floor(total/60)%60,s=total%60;
  return h?`${h}小时${m}分`:(m?`${m}分${s}秒`:`${s}秒`);
}

/* ---------- 导航 ---------- */
function positionPill(){
  const nav=$('#nav'),pill=nav.querySelector('.nav-pill'),active=nav.querySelector('button.active');
  if(!pill)return;
  if(!active||!active.offsetParent){pill.style.opacity='0';return;}
  pill.style.opacity='1';
  pill.style.width=active.offsetWidth+'px';
  pill.style.height=active.offsetHeight+'px';
  pill.style.transform=`translate(${active.offsetLeft}px,${active.offsetTop}px)`;
}
function switchPage(name){
  page=name;
  $$('.page').forEach(e=>{e.hidden=e.id!==name;});
  $$('nav button').forEach(e=>e.classList.toggle('active',e.dataset.page===name||name==='viewer'&&e.dataset.page==='library'));
  $('#heading').textContent=(document.body.classList.contains('windows')?HEADINGS.windows:HEADINGS.android)[name];
  const target=$('#'+name);
  target.classList.remove('entering');
  void target.offsetWidth;
  target.classList.add('entering');
  positionPill();
  if(name==='viewer'&&map){[60,380,700].forEach(d=>setTimeout(()=>map.invalidateSize(),d));}
  // 照片页的匹配位置地图可能是在页面隐藏时建起来的，切回来时补一次尺寸校正。
  if(name==='photos'&&photoMap){[60,380,700].forEach(d=>setTimeout(()=>photoMap.invalidateSize(),d));}
}
$$('nav button').forEach(b=>b.onclick=()=>switchPage(b.dataset.page));
let resizeTimer;
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(positionPill,120);});

/* ---------- 状态刷新 ---------- */
function renderElapsed(){
  const seconds=state.active&&state.started?Math.max(0,Math.floor((Date.now()-state.started)/1000)):0;
  $('#elapsed').textContent=elapsedText(seconds);
}
async function refresh(){
  state=await api('state');
  document.body.classList.toggle('android',state.platform==='android');
  document.body.classList.toggle('windows',state.platform==='windows');
  if(state.platform==='windows'&&page==='record')switchPage('library');
  const recording=!!state.active&&!state.finishing;
  document.body.classList.toggle('recording',recording);

  $('#point-count').textContent=state.count||0;
  renderElapsed();
  const label=state.finishing?'正在保存…':state.active?(state.single?'结束单点定位':'结束并保存'):'开始记录';
  $('#record-action-label').textContent=label;
  $('#record-action').setAttribute('aria-label',state.finishing?'正在保存路径':state.active?'结束并保存路径':'开始记录');
  if(state.island){$('#island-status').textContent=state.island.status;$('#island-enabled').checked=state.island.enabled;}
  $('#last-time').textContent=clock(state.last);
  $('#record-status').textContent=state.finishing?'正在整理路径…':state.active?(state.single?'正在获取单点位置…':'记录中 · 保持沿途的新鲜位置'):'准备就绪';
  $('#record-action').disabled=!!state.finishing;
  $('#single-action').disabled=!!state.finishing||!!state.active;
  $$('.mode').forEach(b=>b.classList.toggle('selected',+b.dataset.mode===(state.mode||0)));
  if(state.error&&state.error!==window.lastError){toast(state.error);window.lastError=state.error;}

  const key=JSON.stringify(state.routes);
  if(key!==lastRoutes){lastRoutes=key;renderRoutes(state.routes||[]);}
  if(state.job){
    const j=state.job;
    $('#job-status').textContent=j.status;
    $('#job-progress').value=j.progress||0;
    $('#preview').disabled=!!j.busy;
    // 写入按钮现在在匹配位置面板里（地图下方）：判定条件不变，仍是「非忙 && 预览就绪」，
    // 另加电脑端限制——写入只在电脑端可用，手机端该面板整个隐藏，按钮保持禁用。
    $('#write').disabled=state.platform!=='windows'||!!j.busy||!j.ready;
    $('#cancel-job').hidden=!j.busy;
    const chip=$('#job-state-chip');
    const phase=j.busy?['busy','处理中']:j.ready?['done','预览就绪']:/失败|错误|异常|请/.test(j.status||'')&&j.progress===0?['fail','需处理']:['idle','待开始'];
    chip.textContent=phase[1];
    chip.className='state-chip '+phase[0];
    if(JSON.stringify(j.rows)!==jobKey){
      jobKey=JSON.stringify(j.rows);
      renderPhotoRows(j.rows||[]);
    }
    if(JSON.stringify(j.written)!==writtenKey){writtenKey=JSON.stringify(j.written);renderWritten(j.written);}
    // 电脑端常显匹配位置面板（不再依赖有没有图钉/轨迹）：没结果时面板里显示占位提示，
    // 地图实例仍是懒初始化——占位阶段不建图，也就不会白白加载瓦片。
    const points=photoPoints(j),tracks=photoTracks(j);
    const show=state.platform==='windows';
    const withData=points.length>0||tracks.length>0;
    $('#photo-map-panel').hidden=!show;
    if(!show||!withData)resetPhotoMap(show);
    const pointKey=JSON.stringify([points,tracks]);
    if(show&&withData&&pointKey!==pointsKey){
      pointsKey=pointKey;
      renderPhotoMap(points,tracks);
    }
  }else{
    // 没有任务时把面板收回兜底状态：保留面板（电脑端常显），清空地图并重置判据，下次预览会重新建图。
    resetPhotoMap(state.platform==='windows');
  }
  const pk=JSON.stringify(state.prefs||{});
  if(pk!==prefsKey){prefsKey=pk;prefs=state.prefs||{};applyPrefs();}
  const photoKey=JSON.stringify(state.photos||{});
  if(photoKey!==photosKey){photosKey=photoKey;renderPhotoList(state.photos);}
  updateSteps();
}

/* ---------- 路径库 ---------- */
function trackLabel(r){
  return `${r.mode==='single'?'单点补录 · ':''}${date(r.started)} ${clock(r.started)} · ${r.count}点`;
}
// 轨迹多选：勾选状态按 id 保留，重绘时不丢用户的选择。
function renderTrackPicker(routes){
  const picker=$('#track-picker');
  const checked=new Set(selectedTracks());
  picker.replaceChildren();
  const selectable=routes.filter(r=>r.state!=='recording');
  if(!selectable.length){
    const hint=document.createElement('div');
    hint.className='empty-hint';
    hint.textContent='路径库还没有可用轨迹';
    picker.append(hint);
    updateSteps();
    return;
  }
  for(const r of selectable){
    const row=document.createElement('label');
    row.className='track-item'+(checked.has(r.id)?' picked':'');
    const box=document.createElement('input');
    box.type='checkbox';box.checked=checked.has(r.id);box.dataset.track=r.id;
    const name=document.createElement('span');
    name.className='track-name';name.textContent=trackLabel(r);
    const tag=document.createElement('span');
    tag.className='track-tag';tag.textContent=r.mode==='single'?'单点':'连续';
    row.append(box,name,tag);
    row.onclick=event=>{
      event.preventDefault();
      const next=!box.checked;
      box.checked=next;
      row.classList.toggle('picked',next);
      updateSteps();
    };
    picker.append(row);
  }
  updateSteps();
}
function selectedTracks(){
  return $$('#track-picker input[data-track]').filter(b=>b.checked).map(b=>b.dataset.track);
}
function trackLabels(){
  const map={};
  for(const r of (state.routes||[]))map[String(r.id)]=trackLabel(r);
  return map;
}
$('#tracks-all').onclick=()=>{$$('#track-picker input[data-track]').forEach(b=>{b.checked=true;b.closest('.track-item')?.classList.add('picked');});updateSteps();};
$('#tracks-none').onclick=()=>{$$('#track-picker input[data-track]').forEach(b=>{b.checked=false;b.closest('.track-item')?.classList.remove('picked');});updateSteps();};

/* 曲线生成方式：两条路都在电脑端做第二步，区别只是合成一条还是各成一条。 */
function mergeTracks(){return prefs.trackMode==='merge';}
function applyTrackMode(){
  const merge=mergeTracks();
  $$('#track-mode .seg').forEach(b=>b.setAttribute('aria-checked',String((b.dataset.tracks==='merge')===merge)));
  $('#track-mode-note').textContent=merge
    ?'按时间把所选轨迹的节点串成一条曲线。单点补录不参与合并；两段之间的空档超过 120 秒时，落在其中的照片会标为长间隔估算。'
    :'每条轨迹各自生成一条曲线，为每张照片按时间证据强度择优，互不相连。';
}
$$('#track-mode .seg').forEach(b=>b.onclick=()=>attempt(async()=>{
  await api('prefs',{key:'trackMode',value:b.dataset.tracks});
  prefs.trackMode=b.dataset.tracks;
  applyTrackMode();
}));

function renderRoutes(routes){
  $('#route-count').textContent=`${routes.length}段旅程 · 原始数据与平滑路径一同保存`;
  const points=routes.reduce((sum,r)=>sum+(r.count||0),0);
  $('#stat-routes').textContent=routes.length;
  $('#stat-points').textContent=points;
  $('#stat-latest').textContent=routes.length?shortDate(routes.map(r=>r.started).sort((a,b)=>b-a)[0]):'—';
  $('#empty').hidden=routes.length>0;
  $('#routes').replaceChildren();
  let order=0;
  for(const r of routes){
    const card=document.createElement('article');
    card.className='route-card';
    card.style.animationDelay=Math.min(order++*45,360)+'ms';

    const top=document.createElement('div');top.className='route-top';
    const tile=document.createElement('div');tile.className='date-tile';
    const day=document.createElement('b'),mon=document.createElement('span');
    const started=new Date(r.started);
    day.textContent=started.getDate();mon.textContent=`${started.getMonth()+1}月`;
    tile.append(day,mon);

    const title=document.createElement('div');title.className='route-title';
    const tb=document.createElement('b'),ts=document.createElement('small');
    tb.textContent=(r.mode==='single'?'单点补录 · ':'')+dayLabel(r.started);
    const span=clock(r.started)+' — '+(r.ended?clock(r.ended):r.state==='recording'?'记录中':'待检查');
    const dur=r.ended?durationText(r.ended-r.started):'';
    ts.textContent=dur?`${span} · ${dur}`:span;
    title.append(tb,ts);

    const badge=document.createElement('span');
    badge.className='badge '+(r.state==='recording'?'live':r.state==='error'?'warn':'ok');
    badge.textContent=r.state==='recording'?'记录中':r.state==='error'?'文件异常':'已保存';
    top.append(tile,title,badge);

    const body=document.createElement('div');body.className='route-body';
    const meta=document.createElement('p');meta.className='route-meta';
    const mp=document.createElement('span');mp.className='pill';mp.textContent=`${r.count} 个节点`;
    const ms=document.createElement('span');ms.textContent=r.state==='recording'?'结束后自动平滑':'已保存到本机';
    meta.append(mp,ms);

    const actions=document.createElement('div');actions.className='actions';
    for(const [text,fn] of [['查看',()=>openRoute(r.id)],['导出',()=>api('export',{id:r.id})],['删除',()=>confirmDelete(r.id)]]){
      const btn=document.createElement('button');
      btn.textContent=text;
      btn.className=text==='查看'?'soft':text==='删除'?'danger':'soft';
      btn.disabled=r.state==='recording'&&text!=='查看';
      btn.onclick=()=>attempt(fn);
      actions.append(btn);
    }
    body.append(meta,actions);
    card.append(top,body);
    $('#routes').append(card);
  }
  renderTrackPicker(routes);
}
function confirmDelete(id){
  $('#confirm').showModal();
  $('#delete-route').onclick=()=>attempt(async()=>{await api('delete',{id});$('#confirm').close();await refresh();toast('路径已删除');});
}
$('#keep-route').onclick=()=>$('#confirm').close();

/* ---------- 记录动作 ---------- */
$('#single-action').onclick=()=>attempt(async()=>{
  await api('single');
  setTimeout(()=>attempt(refresh),500);
  toast('正在获取当前位置，成功后自动保存；两分钟无定位则结束。');
});
$('#record-action').onclick=()=>attempt(async()=>{
  const stop=state.active;
  await api(stop?'stop':'start');
  setTimeout(()=>attempt(refresh),500);
  if(stop){switchPage('library');toast('正在保存本次路径');}
});
$$('[data-mode]').forEach(b=>b.onclick=()=>attempt(async()=>{await api('mode',{value:+b.dataset.mode});await refresh();}));
$('#app-settings').onclick=()=>attempt(()=>api('settings'));
$('#battery').onclick=()=>attempt(()=>api('battery'));
$('#import').onclick=()=>attempt(async()=>{const r=await api('import');if(!r.cancelled){await refresh();toast('已导入路径');}});

/* ---------- 沿途回看 ---------- */
function color(i){return `hsl(${i*137.507764%360} 68% 43%)`;}
async function openRoute(id){
  payload=await api('view',{id});
  routeId=id;
  node=Math.max(0,payload.points.length-1);
  $('#view-title').textContent=payload.points.length
    ?`${date(payload.points[0].t)} · ${payload.points.length}个节点 · ${payload.mode==='single'?'单点补录':'连续轨迹'}`
    :'尚未收到定位';
  $('#export-view').disabled=payload.smoothing==='pending';
  // 第二步（插值成曲线）由电脑端在选中路径时完成；手机端导出的 CLP 只有第一步结果。
  const curve=payload.curve;
  $('#curve-note').classList.toggle('live',!!curve);
  $('#curve-note').textContent=curve
    ?`平滑曲线 ${curve.version||'pchip-4d-v2'}：电脑端按这 ${payload.points.length} 个节点生成，节点之间为曲线。`
    :'节点之间按直线连接：手机端只完成滤除定位漂移，平滑曲线由电脑端在选中该路径时生成。';
  $('#node-slider').max=Math.max(0,node);
  $('#node-picker').replaceChildren();
  payload.points.forEach((p,i)=>{
    const o=document.createElement('option');
    o.value=i;o.textContent=`第${i+1}点 · ${clock(p.t)}`;
    $('#node-picker').append(o);
  });
  switchPage('viewer');
  if(!map){
    map=L.map('map',{zoomControl:true,attributionControl:true});
    tileLayer=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
    tileLayer.on('tileerror',()=>$('#map-status').textContent='底图暂不可用 · 当前显示本地轨迹与WGS84坐标');
    tileLayer.on('tileload',()=>$('#map-status').textContent='WGS84 · 拖动地图或缩放查看位置');
    layer=L.layerGroup().addTo(map);
  }
  map.invalidateSize();
  if(payload.points.length)map.fitBounds(payload.points.map(p=>[p.lat,p.lon]),{padding:[35,35],maxZoom:18});
  else map.setView([36.05,103.85],13);
  renderTrack();
}
function curvePosition(t,a,b){
  const c=payload.curve;
  if(!c||!c.times.length)return [a.lat+(b.lat-a.lat)*(t-a.t)/(b.t-a.t),a.lon+(b.lon-a.lon)*(t-a.t)/(b.t-a.t)];
  let lo=0,hi=c.times.length-1;
  while(lo<hi){const mid=(lo+hi)>>1;if(c.times[mid]<t)lo=mid+1;else hi=mid;}
  if(c.times[lo]===t)return [c.values[0][lo],c.values[1][lo]];
  const i=Math.max(0,lo-1),j=lo,h=c.times[j]-c.times[i],u=(t-c.times[i])/h;
  return [0,1].map(axis=>(2*u**3-3*u*u+1)*c.values[axis][i]+(u**3-2*u*u+u)*h*c.slopes[axis][i]+(-2*u**3+3*u*u)*c.values[axis][j]+(u**3-u*u)*h*c.slopes[axis][j]);
}
function detailCell(label,value,wide){
  const cell=document.createElement('div');
  cell.className='cell'+(wide?' wide':'');
  const span=document.createElement('span'),b=document.createElement('b');
  span.textContent=label;b.textContent=value;
  cell.append(span,b);
  return cell;
}
function renderDetail(p){
  const box=$('#node-detail');
  box.replaceChildren();
  if(!p){
    const empty=document.createElement('div');
    empty.className='empty-cell';
    empty.textContent='尚无定位点';
    box.append(empty);
    return;
  }
  box.append(detailCell('定位时间',clock(p.t)));
  box.append(detailCell('海拔',p.alt==null?'未知':p.alt.toFixed(1)+' 米'));
  box.append(detailCell('定位来源',p.provider==='gps'?'卫星':p.provider==='network'?'网络':'未知'));
  box.append(detailCell('原始精度',p.hacc==null?'未知':p.hacc.toFixed(1)+' 米'));
  box.append(detailCell('平滑修正',(p.correctionMeters||0).toFixed(1)+' 米'));
  box.append(detailCell('WGS84 坐标',`${p.lat.toFixed(7)}, ${p.lon.toFixed(7)}`,true));
}
function renderTrack(){
  if(!payload||!map)return;
  layer.clearLayers();
  const ps=payload.points.slice(0,node+1);
  const last=Math.max(0,payload.points.length-1);
  $('#node-slider').value=node;
  $('#node-slider').style.setProperty('--fill',(last?node/last*100:0)+'%');
  $('#node-picker').value=node;
  $('#node-number').textContent=`${ps.length} / ${payload.points.length}`;
  $('#prev-node').disabled=node<=0;
  $('#next-node').disabled=node>=payload.points.length-1;

  if($('#show-raw').checked&&payload.rawPoints){
    let segment=[];
    payload.rawPoints.slice(0,node+1).forEach((p,i,raw)=>{
      if(i&&p.t-raw[i-1].t>120000){L.polyline(segment,{color:'#8b9690',weight:1.5,dashArray:'4 5'}).addTo(layer);segment=[];}
      segment.push([p.lat,p.lon]);
    });
    L.polyline(segment,{color:'#8b9690',weight:1.5,dashArray:'4 5'}).addTo(layer);
  }

  ps.forEach((p,i)=>{
    if(i){
      const segment=[];
      for(let k=0;k<=12;k++)segment.push(curvePosition(ps[i-1].t+(p.t-ps[i-1].t)*k/12,ps[i-1],p));
      L.polyline(segment,{color:color(i),weight:3,opacity:.85,dashArray:p.t-ps[i-1].t>120000?'6 6':null}).addTo(layer);
    }
    L.circleMarker([p.lat,p.lon],{radius:i===node?7:3.5,color:'#fff',weight:1,fillColor:color(i),fillOpacity:1})
      .on('click',()=>{node=i;renderTrack();})
      .bindTooltip(`第${i+1}点 · ${clock(p.t)}`)
      .addTo(layer);
  });

  const p=ps[ps.length-1];
  renderDetail(p);
  if(p&&payload.rawPoints){
    const r=payload.rawPoints[node];
    if(r&&r.hacc!=null)L.circle([r.lat,r.lon],{radius:r.hacc,color:'#839089',weight:1,fillOpacity:.035,interactive:false}).addTo(layer);
  }
}
$('#node-slider').oninput=e=>{node=+e.target.value;renderTrack();};
$('#node-picker').onchange=e=>{node=+e.target.value;renderTrack();};
$('#prev-node').onclick=()=>{node=Math.max(0,node-1);renderTrack();};
$('#next-node').onclick=()=>{node=Math.min(payload.points.length-1,node+1);renderTrack();};
$('#show-raw').onchange=renderTrack;
$('#back-library').onclick=()=>switchPage('library');
$('#export-view').onclick=()=>attempt(()=>api('export',{id:routeId}));
document.addEventListener('keydown',e=>{
  if(page!=='viewer'||!payload||!payload.points.length)return;
  if(e.target.closest('input,select,textarea,button'))return;
  if(e.key==='ArrowLeft'){node=Math.max(0,node-1);renderTrack();}
  else if(e.key==='ArrowRight'){node=Math.min(payload.points.length-1,node+1);renderTrack();}
});

/* ---------- 照片补录 ---------- */
// 契约（第 3 节）：rows[i] = [序号, 照片, 使用轨迹, 匹配结果, 坐标]，第 0 位是后端给的序号。
function renderPhotoRows(rows){
  const body=$('#photo-rows');
  pickedSpot=null;
  body.replaceChildren();
  (rows||[]).slice(0,2000).forEach(r=>{
    const tr=document.createElement('tr');
    for(const value of r||[]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    // 行 → 图钉：行号就用后端给的序号，图钉按同一个编号索引；缺序号的行不参与联动。
    const n=spotNumber(r&&r[0]);
    if(n!=null){
      tr.dataset.n=String(n);
      tr.onclick=()=>pickSpot(n);
    }
    body.append(tr);
  });
}
// 序号可能是字符串（契约），统一取成整数；缺失或无法解析时返回 null。
function spotNumber(value){
  const n=parseInt(value,10);
  return Number.isFinite(n)?n:null;
}
/* 匹配位置地图：手机端没有 points/tracks，全部按空数组处理。 */
function photoPoints(job){
  const list=(job||{}).points;
  if(!Array.isArray(list))return [];
  return list.filter(p=>p&&coord(p.lat)!=null&&coord(p.lon)!=null);
}
function photoTracks(job){
  const list=(job||{}).tracks;
  if(!Array.isArray(list))return [];
  return list.map(t=>({label:t&&t.label,points:Array.isArray(t&&t.points)?t.points.filter(p=>Array.isArray(p)&&coord(p[0])!=null&&coord(p[1])!=null):[]}));
}
function coord(value){
  const n=Number(value);
  return Number.isFinite(n)?n:null;
}
// 图钉样式：白底蓝描边圆形 + 居中编号，两位数三位数都放得下。
function photoPinIcon(n,picked){
  return L.divIcon({
    className:'photo-pin'+(picked?' picked':''),
    html:`<span aria-hidden="true">${n}</span>`,
    iconSize:[26,26],
    iconAnchor:[13,13]
  });
}
// 有结果时画轨迹折线 + 带编号图钉 + 行/图钉双向联动 + fitBounds（见 renderPhotoMap）。
// 没有结果（或不是电脑端）：面板按平台显隐，占位提示重新盖住地图，摘要归零，
// 并擦掉上一次的图钉/曲线；地图实例保留，pointsKey 重置以便下次重新建图与定视野。
function clearPhotoMapLayers(){
  if(!photoLayers)return;
  photoLayers.clearLayers();
  photoMarkers=new Map();
  pickedSpot=null;
}
function resetPhotoMap(showPanel){
  $('#photo-map-panel').hidden=!showPanel;
  $('#photo-map-empty').hidden=false;
  $('#photo-map-summary').textContent='0 张';
  // 手机端：整块收起，顺手把地图清干净，免得切回电脑端时闪出上一次的图钉。
  if(!showPanel){clearPhotoMapLayers();photoMapShown=false;pointsKey='';return;}
  if(photoMapShown)clearPhotoMapLayers();
  photoMapShown=false;
  pointsKey='';
}
function ensurePhotoMap(){
  const el=$('#photo-map');
  if(!photoMap){
    if(!el||!window.L)return null;
    try{
      photoMap=L.map(el,{zoomControl:true,attributionControl:true});
      const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(photoMap);
      // 与查看页同一套瓦片；底图失败只降级显示本机轨迹，不抛错。
      tiles.on('tileerror',()=>{});
    }catch(e){photoMap=null;return null;}
    photoLayers=L.layerGroup().addTo(photoMap);
    photoMarkers=new Map();
  }
  photoMap.invalidateSize();
  return photoMap;
}
// 重绘：地图实例只建一次，标记每次清干净再画。
function renderPhotoMap(points,tracks){
  if(!ensurePhotoMap())return;
  photoLayers.clearLayers();
  photoMarkers=new Map();
  pickedSpot=null;
  const bounds=[];
  for(let i=0;i<tracks.length;i++){
    const line=tracks[i].points;
    if(line.length<2)continue;
    L.polyline(line,{color:color(i),weight:2.5,opacity:.55,lineJoin:'round'}).addTo(photoLayers);
    for(const p of line)bounds.push(p);
  }
  for(let i=0;i<points.length;i++){
    const p=points[i];
    const n=spotNumber(p.n);
    if(n==null)continue;
    const lat=coord(p.lat),lon=coord(p.lon);
    const marker=L.marker([lat,lon],{icon:photoPinIcon(n,false),title:`第${n}张 · ${p.relative||''}`,alt:`第${n}张照片的匹配位置`})
      .on('click',()=>pickSpot(n))
      .addTo(photoLayers);
    if(p.relative)marker.bindTooltip(`${n} · ${p.relative}`,{direction:'top',offset:[0,-14]});
    photoMarkers.set(n,marker);
    bounds.push([lat,lon]);
  }
  const summary=`${points.length} 张${tracks.length?` · ${tracks.length} 条曲线`:''}`;
  $('#photo-map-summary').textContent=summary;
  $('#photo-map-empty').hidden=true;
  photoMapShown=points.length>0||tracks.length>0;
  if(!bounds.length){photoMap.setView([36.05,103.85],13);return;}
  // 只有一张照片时经纬度范围退化为一个点，fitBounds 会顶到 maxZoom，这里直接给一个街区级视野。
  if(bounds.length===1)photoMap.setView(bounds[0],15);
  else photoMap.fitBounds(bounds,{padding:[35,35],maxZoom:17});
}
// 单选高亮：行与图钉共用同一个 picked 状态，任何时候最多一处高亮。
function pickSpot(n){
  if(n==null)return;
  const row=$('#photo-rows').querySelector(`tr[data-n="${n}"]`);
  const marker=photoMarkers?photoMarkers.get(n):null;
  if(!row&&!marker)return;
  if(pickedSpot!=null){
    $('#photo-rows').querySelector(`tr[data-n="${pickedSpot}"]`)?.classList.remove('picked');
    const previous=photoMarkers?photoMarkers.get(pickedSpot):null;
    if(previous)previous.setIcon(photoPinIcon(pickedSpot,false));
  }
  pickedSpot=n;
  row?.classList.add('picked');
  row?.scrollIntoView({block:'nearest'});
  if(marker){
    marker.setIcon(photoPinIcon(n,true));
    photoMap.panTo(marker.getLatLng());
  }
}
function photoCount(){return (state.photos&&state.photos.count)||0;}
function hasPhotos(){return photoCount()>0||!!$('#photos-path').value;}
function updateSteps(){
  const items=[...document.querySelectorAll('#steps li')];
  if(!items.length)return;
  const tracks=selectedTracks().length;
  const photos=hasPhotos();
  const ready=!!(state.job&&state.job.ready);
  const active=!tracks?0:!photos?1:2;
  $('#track-count').textContent=tracks?`已选 ${tracks} 条`:'未选择';
  items.forEach((li,i)=>{
    li.classList.toggle('active',i===active);
    li.classList.toggle('done',i<active||(i===2&&ready));
  });
}
function renderPhotoList(summary){
  const box=$('#photo-list');
  const count=(summary&&summary.count)||0;
  box.classList.toggle('ready',count>0);
  box.replaceChildren();
  if(!count){
    box.textContent=`把 ${PHOTO_LABEL} 文件拖到窗口任意位置即可导入`;
    $('#photo-count').textContent='尚未导入';
    $('#photo-source-note').textContent=$('#photos-path').value?'当前改用下方目录作为照片来源。':'';
    return;
  }
  const names=(summary.names||[]).slice(0,80);
  for(const name of names){
    const row=document.createElement('div');row.className='photo-row';
    const dot=document.createElement('span');dot.textContent='·';
    const label=document.createElement('b');label.textContent=name;
    row.append(dot,label);box.append(row);
  }
  if(count>names.length){
    const more=document.createElement('div');
    more.className='photo-more';
    more.textContent=`…还有 ${count-names.length} 张`;
    box.append(more);
  }
  if(summary.root){
    const root=document.createElement('div');
    root.className='photo-root';
    root.textContent=`相对路径基准：${summary.root}`;
    box.append(root);
  }
  $('#photo-count').textContent=`已导入 ${count} 张`;
  $('#photo-source-note').textContent='已导入的照片优先于下方目录；写入时按上面的相对路径基准保留目录结构。';
}
$$('[data-pick]').forEach(b=>b.onclick=()=>attempt(async()=>{
  const r=await api('pick',{kind:b.dataset.pick});
  if(r.path)$(`#${b.dataset.pick}-path`).value=r.path;
  updateSteps();
}));
$('#photos-pick').onclick=()=>attempt(async()=>{
  if(state.platform!=='windows')throw Error('选择照片只在电脑端可用');
  const r=await api('photos-pick');
  if(r.cancelled)return;
  await refresh();
  toast(r.added?`已导入 ${r.added} 张照片${r.skipped?`，跳过 ${r.skipped} 个不支持的文件`:''}`:'没有新增照片');
});
$('#photos-clear').onclick=()=>attempt(async()=>{
  if(state.platform!=='windows')return;
  await api('photos-clear');
  await refresh();
  toast('已清空导入的照片');
});
function options(){
  return {
    tracks:selectedTracks(),
    trackLabels:trackLabels(),
    photos:$('#photos-path').value,
    output:$('#output-path').value,
    offset:$('#offset').value,
    correction:$('#correction').value,
    overwrite:$('#overwrite').checked,
    inPlace:writeInPlace(),
    mergeTracks:mergeTracks()
  };
}
$('#preview').onclick=()=>attempt(async()=>{
  if(!selectedTracks().length)throw Error('请至少勾选一条轨迹。');
  if(!hasPhotos())throw Error('请先导入照片：把照片拖进窗口、点「选择照片」，或选择一个照片目录。');
  await api('preview',options());await refresh();
});
$('#write').onclick=()=>attempt(async()=>{await api('write',options());await refresh();});
$('#cancel-job').onclick=()=>attempt(()=>api('cancel'));
$('#offset').oninput=()=>{$('#offset').dataset.touched='1';};

/* ---------- 设置 ---------- */
$('#island-enabled').onchange=()=>attempt(async()=>{await api('island-toggle',{enabled:$('#island-enabled').checked});await refresh();});
$('#island-check').onclick=()=>attempt(async()=>{const r=await api('island-check');$('#island-status').textContent=r.status;});
$('#island-settings').onclick=()=>attempt(()=>api('notification-settings'));

/* ---------- 超级岛诊断 ---------- */
// 每个闸门都显示真实取值，避免“已具备条件”这类含糊结论掩盖具体卡点。
function islandGate(label,value,state){
  const cell=document.createElement('div');
  cell.className='gate '+(state||'warn');
  const dot=document.createElement('i'),box=document.createElement('div');
  const title=document.createElement('b'),detail=document.createElement('span');
  title.textContent=label;detail.textContent=value;
  box.append(title,detail);cell.append(dot,box);
  return cell;
}
function triState(value,okText,noText,unknownText,error){
  if(value==='true')return [okText,'pass'];
  if(value==='false')return [noText,'fail'];
  return [(unknownText||'未知')+(error?' · '+error:''),'warn'];
}
function renderIslandDiagnostics(d){
  const gates=d.gates||{},device=d.device||{},last=d.last||{};
  const box=$('#island-gates');
  box.replaceChildren();
  box.append(islandGate('尝试开关',gates.switch==='on'?'已开启':'已关闭',gates.switch==='on'?'pass':'fail'));
  box.append(islandGate('通知权限',gates.notifications?'已授权':'未授权',gates.notifications?'pass':'fail'));
  box.append(islandGate('焦点通知协议',`读到 ${gates.protocol}（需 ≥3）`+(gates.protocolError?` · ${gates.protocolError}`:''),gates.protocol>=3?'pass':'fail'));
  const flag=triState(gates.featureFlag,'系统已开启','系统未开启','读取被系统限制',gates.featureFlagError);
  box.append(islandGate('系统超级岛',flag[0],flag[1]));
  const focus=triState(gates.canShowFocus,'已授权','未授权','未确认',gates.canShowFocusError);
  box.append(islandGate('应用焦点通知权限',gates.canShowFocus==='true'?`已授权（${gates.canShowFocusVia||'系统'}）`:focus[0],focus[1]));
  const importance={high:'高',default:'默认',low:'低',min:'最低',none:'已关闭',absent:'尚未创建',unknown:'未知'}[gates.channelImportance]||gates.channelImportance;
  box.append(islandGate('记录通知渠道',importance,gates.channelImportance==='low'||gates.channelImportance==='min'?'warn':'pass'));
  box.append(islandGate('业务标识',gates.business||'—','pass'));
  box.append(islandGate('设备',`${device.manufacturer||''} ${device.model||''} · Android ${device.androidSdk||''}`, 'warn'));
  box.append(islandGate('系统版本',device.incremental||device.display||'—','warn'));
  $('#island-business').value=gates.business||'';
  const attempt=last.payload?`最近一次已下发参数（${last.at||''}），共 ${last.payload.length} 字符。`
    :last.at?`最近一次未下发参数（${last.at}）：${last.error||'未知原因'}。`
    :'本次开机后还没有下发过超级岛参数。';
  $('#island-test-result').textContent=`${d.status||''}\n${attempt}`;
  $('#island-extra').hidden=false;
}
$('#island-diagnose').onclick=()=>attempt(async()=>{renderIslandDiagnostics(await api('island-diagnose'));});
$('#island-test').onclick=()=>attempt(async()=>{
  const r=await api('island-test');
  await attempt(async()=>renderIslandDiagnostics(await api('island-diagnose')));
  $('#island-test-result').textContent=`已发送一条30秒后自动消失的测试通知。${r.blockedBy?'当前卡在：'+r.blockedBy:'条件已满足，请看状态栏是否上岛。'}\n${r.status||''}`;
  toast('测试通知已发送，请看状态栏或超级岛');
});
$('#island-business-save').onclick=()=>attempt(async()=>{
  const r=await api('island-business',{value:$('#island-business').value});
  toast(`业务标识已保存：${r.business}`);
});

/* ---------- 写入结果预览 ---------- */
const METHOD_LABEL={single:'单点固定位置',interpolated:'平滑曲线插值','curve-long-gap':'长间隔估算'};
function renderWritten(written){
  const list=written||[];
  $('#written-panel').hidden=list.length===0;
  $('#written-summary').textContent=`${list.length} 张`;
  if(!list.length)return;
  const body=$('#written-rows');
  body.replaceChildren();
  for(const item of list){
    const tr=document.createElement('tr');
    const cells=[
      item.n==null?'—':String(item.n),
      item.relative,
      item.track||'—',
      item.lat==null?'—':item.lat.toFixed(7),
      item.lon==null?'—':item.lon.toFixed(7),
      item.alt==null?'未知':`${item.alt.toFixed(1)} 米`,
      item.captureUtc||'—',
      METHOD_LABEL[item.method]||item.method||'—'
    ];
    for(const value of cells){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    body.append(tr);
  }
}

/* ---------- 写入方式（电脑端设置） ---------- */
function writeInPlace(){return !!prefs.writeInPlace;}
function applyWriteMode(){
  const inPlace=writeInPlace();
  $$('#write-mode .seg').forEach(b=>b.setAttribute('aria-checked',String((b.dataset.mode==='inplace')===inPlace)));
  $('#write-mode-note').textContent=inPlace
    ?'当前会直接改写原始照片：先复制到原片同目录的临时文件，写入并读回验证通过后才替换原片，任何失败都不会动到原片。建议同时设置备份目录。'
    :'当前把 GPS 写入独立输出目录，原始照片保持不动。';
  $('#output-label').textContent=inPlace?'备份目录（留空则不备份）':'输出副本目录';
  $('#output-path').placeholder=inPlace?'可选：改写前把原片备份到这里':'选择独立的输出文件夹';
  $('#write').textContent=inPlace?'覆盖原始照片':'写入照片副本';
  $('#overwrite-label').textContent=inPlace?'覆盖原片中已有的GPS':'覆盖照片副本中已有的GPS';
  const hint=$('#mode-hint');
  if(inPlace){hint.textContent='注意：覆盖模式会改变原始文件内容，请先确认照片目录选对，必要时保留备份。';hint.classList.add('warn');}
  else{hint.textContent='';hint.classList.remove('warn');}
}
function applyPrefs(){
  const offset=prefs.defaultOffset||'+08:00';
  $('#default-offset').value=offset;
  if(!$('#offset').dataset.touched)$('#offset').value=offset;
  applyWriteMode();
  applyTrackMode();
}
async function setPref(key,value){
  if(state.platform!=='windows'){prefs=Object.assign({},prefs,{[key]:value});applyPrefs();return;}
  const r=await api('prefs',{key,value});
  prefs=r||prefs;applyPrefs();
}
$$('#write-mode .seg').forEach(b=>b.onclick=()=>attempt(async()=>{
  const wantInPlace=b.dataset.mode==='inplace';
  if(wantInPlace&&!writeInPlace()){$('#confirm-mode').showModal();return;}
  await setPref('writeInPlace',wantInPlace);
  updateSteps();
}));
$('#keep-copy').onclick=()=>$('#confirm-mode').close();
$('#accept-inplace').onclick=()=>attempt(async()=>{
  $('#confirm-mode').close();
  await setPref('writeInPlace',true);
  toast('已切换为直接覆盖原始文件；写入前会先做临时副本并读回验证');
});
$('#default-offset-save').onclick=()=>attempt(async()=>{
  const value=$('#default-offset').value.trim()||'+08:00';
  await setPref('defaultOffset',value);
  $('#offset').value=value;$('#offset').dataset.touched='1';
  toast(`默认相机时区已保存：${value}`);
});

/* ---------- 拖入文件：.clp 进路径库，.nef 进待处理照片 ---------- */
function dragHasFiles(event){
  const transfer=event.dataTransfer;
  if(!transfer)return false;
  return [...(transfer.types||[])].includes('Files');
}
function dropzone(show,hint){
  const zone=$('#dropzone');
  if(show){$('#dropzone-hint').textContent=hint||'松手后 .clp 加入路径库，.nef 加入待处理照片';zone.hidden=false;}
  else zone.hidden=true;
}
function bufferToBase64(buffer){
  const bytes=new Uint8Array(buffer);
  let binary='';
  for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));
  return btoa(binary);
}
// 桌面端会把被拖文件的真实路径交回来；NEF 只能走这条路（WebView2 不给页面路径）。
window.__nativeDropReady=false;
window.nativeDropReady=ready=>{window.__nativeDropReady=!!ready;};
// 支持写入 GPS 的照片格式；与 windows/exiftool_io.py 的 SUPPORTED_SUFFIXES 保持一致。
const PHOTO_RE=/\.(nef|dng|jpe?g|png|heic|heif)$/i;
const PHOTO_LABEL='NEF / DNG / JPG / PNG / HEIC';
window.nativeDropFiles=async paths=>{
  const list=(paths||[]).map(String);
  const clp=list.filter(p=>/\.clp$/i.test(p));
  const nef=list.filter(p=>PHOTO_RE.test(p));
  const other=list.length-clp.length-nef.length;
  try{
    if(nef.length){
      const r=await api('photos-add',{paths:nef});
      await refresh();
      switchPage('photos');
      if(!r.added&&r.skipped)throw Error('拖入的照片都不在可读取的位置');
      toast(`已导入 ${r.added} 张照片${r.skipped?`，跳过 ${r.skipped} 个不支持的文件`:''}`);
    }
    if(clp.length){
      const r=await api('import-paths',{paths:clp});
      await refresh();
      if(!nef.length)switchPage('library');
      toast(`已导入 ${r.count} 条轨迹`);
    }
    if(!clp.length&&!nef.length)throw Error(other?'拖入的文件里没有 .clp 路径或受支持的照片':'没有可识别的文件');
  }catch(e){toast(e.message||String(e));}
};
// 没有原生拖放时（例如浏览器里预览）：.clp 仍可用字节通道，照片只能提示改用按钮。
async function importDropped(files){
  const list=(files||[]).filter(f=>/\.clp$/i.test(f.name));
  const nef=(files||[]).filter(f=>PHOTO_RE.test(f.name));
  if(nef.length&&!list.length)throw Error('无法读取被拖文件的路径，请用「选择照片」按钮导入照片');
  if(!list.length)throw Error('拖入的文件里没有 .clp 路径文件');
  if(state.platform!=='windows')throw Error('拖入导入只在电脑端可用');
  if(list.length>1)toast(`一次导入一条轨迹，已取用 ${list[0].name}`);
  const file=list[0];
  if(file.size>32*1024*1024)throw Error('文件超过 32 MB，请改用「导入CLP」按钮');
  const data=bufferToBase64(await file.arrayBuffer());
  await api('import-bytes',{name:file.name,data});
  await refresh();
  switchPage('library');
  toast(`已导入路径：${file.name}`);
}
let dragDepth=0;
window.addEventListener('dragenter',e=>{
  if(!dragHasFiles(e))return;
  e.preventDefault();dragDepth++;
  const names=[...(e.dataTransfer.items||[])].map(i=>i.name||'');
  const clp=names.find(n=>/\.clp$/i.test(n));
  const nef=names.find(n=>PHOTO_RE.test(n));
  dropzone(true,nef?`松手导入照片 ${nef}`:clp?`松手导入路径 ${clp}`:undefined);
});
window.addEventListener('dragover',e=>{if(!dragHasFiles(e))return;e.preventDefault();e.dataTransfer.dropEffect='copy';});
window.addEventListener('dragleave',e=>{
  if(!dragHasFiles(e))return;
  dragDepth=Math.max(0,dragDepth-1);
  if(!dragDepth)dropzone(false);
});
window.addEventListener('drop',e=>{
  if(!dragHasFiles(e))return;
  e.preventDefault();dragDepth=0;dropzone(false);
  // 原生拖放可用时由桌面端回传真实路径，界面不再经手字节流。
  if(window.__nativeDropReady)return;
  attempt(()=>importDropped([...(e.dataTransfer.files||[])]));
});
window.addEventListener('dragend',()=>{dragDepth=0;dropzone(false);});

/* ---------- 启动 ---------- */
async function initialize(){
  try{await refresh();}catch(e){setTimeout(initialize,400);return;}
  switchPage(page);
  requestAnimationFrame(positionPill);
  setTimeout(positionPill,240);
  setInterval(()=>{if(!document.hidden)attempt(refresh);},3000);
  // 表盘秒级自走：记录中每秒本地插值，不必等3秒状态轮询
  setInterval(()=>{if(!document.hidden&&state.active&&!state.finishing)renderElapsed();},1000);
}
initialize();
