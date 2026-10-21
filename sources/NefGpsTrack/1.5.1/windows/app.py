"""途记桌面端窗口：共享本地界面 + 安全的 NEF GPS 写入流水线。

写入不产生表格文件；结果通过 job.rows 与 job.written 回给界面。

支持两种导入：
- 拖入文件：WebView2 不把被拖文件的路径交给页面，因此用 pywebview 的原生拖放
  （body 的 drop 事件）取真实路径，再回调界面。.clp 进路径库，.nef 进待处理照片集。
- 选择文件/目录：.clp 走文件对话框或多选；照片可多选 NEF，也可选整个目录。

可选多条轨迹：为每张照片在候选轨迹中按时间证据强度择优，规则见 batch.pick_track()。

数据位置：1.5.0 起全部放在**安装路径**下的 `data\`，见 paths.py。
"""
import base64,ctypes,json,os,subprocess,sys,threading
from pathlib import Path
from clp_codec import FIXED_KEY
import paths
from library import Library
from batch import Options,common_root,prepare_plan,execute_plan
from exiftool_io import ExifTool, is_supported_photo
from time_match import parse_offset,utc_text

# 拖入 .clp 的字节回退通道上限；NEF 一律走原生路径，不经过字节通道。
MAX_DROP_BYTES = 32 * 1024 * 1024
# 允许通过界面修改的偏好键；默认值与含义见 完整维护文档.md。
PREF_DEFAULTS = {'writeInPlace': False, 'defaultOffset': '+08:00', 'trackMode': 'separate'}
PREF_KEYS = tuple(PREF_DEFAULTS)


class Prefs:
    """界面偏好，保存在数据目录的「程序数据」文件夹：`data\\程序数据\\settings.json`。

    1.5.0 起数据随安装路径走（见 paths.py），不再写 %LOCALAPPDATA%。
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else paths.settings_file()
        self.data = dict(PREF_DEFAULTS)
        for candidate in (self.path, self.path.parent / paths.LEGACY_SETTINGS_NAME):
            try:
                if candidate.is_file():
                    stored = json.loads(candidate.read_text(encoding='utf-8'))
                    if isinstance(stored, dict):
                        self.data.update({k: stored[k] for k in PREF_KEYS if k in stored})
                    break
            except Exception:
                # 损坏的偏好文件不应阻止程序启动，退回默认值。
                self.data = dict(PREF_DEFAULTS)

    def set(self, key, value):
        if key not in PREF_KEYS:
            raise ValueError('不支持的设置项：' + str(key))
        if key == 'writeInPlace':
            self.data[key] = bool(value)
        elif key == 'trackMode':
            # 曲线生成方式：各自成曲线 / 合并为一条。
            self.data[key] = 'merge' if str(value) == 'merge' else 'separate'
        else:
            self.data[key] = str(value or '').strip() or PREF_DEFAULTS[key]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        return dict(self.data)


def _coordinate_text(lat,lon,alt):
    if lat is None or lon is None:return '—'
    place=f'{lat:.7f}, {lon:.7f}'
    return place if alt is None else f'{place} · {alt:.1f}米'


def _path_or_none(value):
    text=str(value or '').strip()
    return Path(text) if text else None


def _dialog_paths(result):
    """统一 pywebview 文件对话框的返回：可能是 None、字符串或序列。"""
    if not result:return []
    if isinstance(result,str):return [result]
    return [str(item) for item in result]


class Api:
    def __init__(self,library=None,prefs=None):
        self.library=library or Library();self.prefs=prefs or Prefs();self.window=None;self.lock=threading.RLock();self.stop=threading.Event();self.plan=None;self.signature=None
        self.photos=[]           # 待处理照片的绝对路径，来自拖入或多选
        self.plan_photos=None    # 预览时的照片清单快照，写入前比对
        self.native_drop=False   # 是否已注册原生拖放
        self.job=dict(busy=False,ready=False,status='先预览匹配，再写入。',progress=0,rows=[],points=[],tracks=[],written=[],inPlace=False)
    # ---------- 照片集 ----------
    def photo_summary(self):
        root=common_root([Path(p) for p in self.photos]) if self.photos else None
        return dict(count=len(self.photos),names=[Path(p).name for p in self.photos[:500]],
                    root=str(root) if root else None)
    def add_photos(self,paths):
        added=0;skipped=0
        known={str(Path(p).resolve()).casefold() for p in self.photos}
        for raw in paths:
            item=Path(str(raw))
            if not is_supported_photo(item) or not item.is_file():
                skipped+=1;continue
            key=str(item.resolve()).casefold()
            if key in known:continue
            known.add(key);self.photos.append(str(item));added+=1
        return dict(added=added,skipped=skipped,photos=self.photo_summary())
    # ---------- 原生拖放 ----------
    def on_native_drop(self,event):
        """pywebview 原生 drop 回调：事件里的 pywebviewFullPath 才是真实路径。"""
        try:
            files=(event or {}).get('dataTransfer',{}).get('files') or []
        except Exception:
            files=[]
        paths=[]
        for item in files:
            path=item.get('pywebviewFullPath') if isinstance(item,dict) else None
            if path:paths.append(str(path))
        if not paths or self.window is None:return
        try:
            self.window.evaluate_js('window.nativeDropFiles('+json.dumps(paths,ensure_ascii=False)+')')
        except Exception:
            pass
    def request(self,action,args=None):
        try:
            with self.lock:return self._request(action,args or {})
        except Exception as e:return {'error':str(e)}
    def _request(self,action,args):
        import webview
        if action=='state':return dict(platform='windows',routes=self.library.list(),job=json.loads(json.dumps(self.job)),prefs=dict(self.prefs.data),photos=self.photo_summary(),nativeDrop=self.native_drop)
        if action=='prefs':return self.prefs.set(str(args.get('key') or ''),args.get('value'))
        if action=='view':return self.library.load(self.library.path(str(args['id'])))
        if action=='cancel':self.stop.set();return {}
        if self.job['busy'] and action in ('delete','import','import-bytes','import-paths','preview','write','photos-add','photos-pick','photos-clear'):raise ValueError('请等待当前处理结束，或先停止处理。')
        if action=='import':
            paths=_dialog_paths(self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,file_types=('加密路径 (*.clp)',)))
            if not paths:return {'cancelled':True}
            return {'id':self.library.import_file(paths[0])}
        if action=='import-paths':
            ids=[]
            for raw in (args.get('paths') or []):
                item=Path(str(raw))
                if item.suffix.lower()!='.clp' or not item.is_file():continue
                ids.append(self.library.import_file(item))
            if not ids:raise ValueError('拖入的文件里没有可用的 .clp 路径文件')
            return {'ids':ids,'count':len(ids)}
        if action=='import-bytes':
            name=str(args.get('name') or '')
            raw=args.get('data') or ''
            try:
                blob=base64.b64decode(raw,validate=True)
            except Exception as exc:
                raise ValueError('拖入的文件无法解码：'+str(exc))
            if len(blob)>MAX_DROP_BYTES:raise ValueError('文件超过 32 MB，请改用「导入」按钮选择文件。')
            return {'id':self.library.import_bytes(name,blob),'name':name}
        if action=='photos-add':
            return self.add_photos(args.get('paths') or [])
        if action=='photos-pick':
            picked=_dialog_paths(self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=True,file_types=('照片 (*.nef;*.dng;*.jpg;*.jpeg;*.png;*.heic;*.heif)',)))
            if not picked:return {'cancelled':True,'photos':self.photo_summary()}
            return self.add_photos(picked)
        if action=='photos-clear':
            self.photos=[];self.plan=None;self.job['ready']=False;return {'photos':self.photo_summary()}
        if action=='delete':self.library.delete(str(args['id']));self.plan=None;self.job['ready']=False;return {}
        if action=='export':
            paths=self.window.create_file_dialog(webview.FileDialog.SAVE,save_filename='NefGpsTrack-'+str(args['id'])[:8]+'.clp',file_types=('加密路径 (*.clp)',))
            if paths:self.library.export(str(args['id']),paths if isinstance(paths,str) else paths[0])
            return {'cancelled':not paths}
        if action=='pick':
            paths=self.window.create_file_dialog(webview.FileDialog.FOLDER)
            return {'path':_dialog_paths(paths)[0] if _dialog_paths(paths) else ''}
        if action=='preview':
            options=self._options(args)
            self.plan=None;self.signature=dict(args);self.plan_photos=tuple(self.photos);self.stop.clear()
            self.job.update(busy=True,ready=False,status='正在匹配照片与所选轨迹…',progress=0,rows=[],written=[],inPlace=options.in_place)
            threading.Thread(target=self._preview,args=(options,dict(args.get('trackLabels') or {})),daemon=True).start();return {}
        if action=='write':
            if self.plan is None or self.signature!=args:raise ValueError('参数已变化，请重新预览匹配。')
            if tuple(self.photos)!=tuple(self.plan_photos or ()):raise ValueError('照片清单已变化，请重新预览匹配。')
            self.stop.clear();self.job.update(busy=True,ready=False,status='正在写入并读回核验…',progress=0,written=[])
            threading.Thread(target=self._write,daemon=True).start();return {}
        raise ValueError('未知操作')
    def _options(self,args):
        from batch import validate_paths
        parse_offset(args['offset']);import math
        correction=float(args['correction'])
        if not math.isfinite(correction):raise ValueError('相机校正须为有限数字')
        ids=[str(item) for item in (args.get('tracks') or []) if str(item).strip()]
        if not ids:raise ValueError('请至少勾选一条轨迹。')
        tracks=tuple(self.library.path(item) for item in ids)
        photos=_path_or_none(args.get('photos'))
        output=_path_or_none(args.get('output'))
        # 照片清单一律以桌面端持有的路径为准，界面不需要回传上百个路径。
        options=Options(tracks,photos,tuple(self.photos),output,args['offset'],correction,
                        bool(args.get('overwrite')),bool(args.get('inPlace')),bool(args.get('mergeTracks')))
        validate_paths(options)
        return options
    def _preview(self,options,labels):
        try:
            def progress(i,n,row):
                with self.lock:self.job.update(progress=i*100/max(1,n),status=f'匹配照片 {i}/{n}')
            plan=prepare_plan(options,FIXED_KEY,ExifTool(),progress=progress,stop=self.stop,labels=labels)
            target='原片' if options.in_place else '副本'
            curve_note='合并为一条曲线' if options.merge_tracks else f'{len(options.tracks)}条曲线'
            # 预览结果同时给出「编号 + 坐标」，界面据此在地图上按编号插图钉。
            pins=[dict(n=r.number,relative=str(r.relative),lat=r.match.point.lat,lon=r.match.point.lon,
                       alt=r.match.point.alt,method=r.match.method,track=r.track_label)
                  for r in plan.rows if r.status=='ready' and r.match is not None]
            with self.lock:
                self.plan=plan
                self.job.update(ready=True,progress=100,
                                status=f'预览完成 · {len(plan.rows)}张照片 · {curve_note} · {sum(r.status=="ready" for r in plan.rows)}张可写入{target}',
                                rows=[[str(r.number),str(r.relative),r.track_label or '—',r.reason,'—'] for r in plan.rows],
                                points=pins,tracks=[dict(t) for t in plan.track_lines],written=[])
        except Exception as e:
            with self.lock:self.job.update(status=str(e),ready=False)
        finally:
            with self.lock:self.job['busy']=False
    def _write(self):
        try:
            def progress(i,n,row):
                with self.lock:self.job.update(progress=i*100/max(1,n),status=f'处理照片 {i}/{n} · {row.result}')
            rows=execute_plan(self.plan,ExifTool(),progress=progress,stop=self.stop)
            written=[dict(n=r.plan.number,relative=str(r.plan.relative),track=r.plan.track_label,lat=r.latitude,lon=r.longitude,alt=r.altitude,
                          method=(r.plan.match.method if r.plan.match else ''),
                          captureUtc=utc_text(r.plan.capture_ms)) for r in rows if r.result=='written']
            count=sum(r.result=='written' for r in rows)
            place='原片已就地改写' if self.job.get('inPlace') else '已生成副本'
            with self.lock:
                self.job.update(progress=100,status=f'完成 · 写入{count}张 · {place}',
                                rows=[[str(r.plan.number),str(r.plan.relative),r.plan.track_label or '—',r.result+' · '+r.detail,_coordinate_text(r.latitude,r.longitude,r.altitude)] for r in rows],
                                written=written)
        except Exception as e:
            with self.lock:self.job['status']=str(e)
        finally:
            with self.lock:self.job['busy']=False;self.job['ready']=False;self.plan=None

class Bridge:
    """Expose only the explicit dispatcher, never native window or library objects."""
    def __init__(self,api):self._api=api
    def request(self,action,args=None):return self._api.request(action,args)

def _message_box(text, title, flags):
    """原生确认框：不引入 GUI 依赖，卸载流程用它。返回用户点的按钮编号。"""
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        return 2  # 无法弹窗时当作取消，绝不静默卸载


def _run_uninstall(silent=False, reg_root=None):
    """卸载：删注册表项、快捷方式，必要时删数据；最后以脱离进程清理安装目录。"""
    from installer_core import remove_shortcut, remove_uninstall_entries  # 见下方 _load_installer_core
    root = paths.install_root()
    data = paths.data_root()
    MB_YESNO, MB_ICONQUESTION, MB_ICONWARNING = 0x04, 0x20, 0x30
    if not silent:
        if _message_box(f'确定要卸载途记吗？\n\n程序位置：{root}', '卸载途记', MB_YESNO | MB_ICONQUESTION) != 6:
            return 0
        remove_data = _message_box(
            f'是否一并删除数据文件夹？\n\n{data}\n\n选「是」会删除路径库（轨迹）与设置；选「否」保留数据。',
            '卸载途记', MB_YESNO | MB_ICONWARNING) == 6
    else:
        remove_data = False
    remove_shortcut()
    remove_uninstall_entries(reg_root)
    if remove_data:
        import shutil
        shutil.rmtree(data, ignore_errors=True)
    # 程序自己删不掉自己：交给一个脱离的 cmd，等本进程退出后再清目录。
    script = f'ping -n 3 127.0.0.1 >nul & rmdir /s /q "{root}"'
    try:
        subprocess.Popen(['cmd', '/c', script], creationflags=0x00000008 | 0x00000200,
                         close_fds=True, cwd=str(Path(os.environ.get('TEMP', '.'))))
    except OSError:
        pass
    return 0


def _load_installer_core():
    """安装器核心：卸载只用到注册表与快捷方式这几支，按相对路径加载。"""
    import importlib.util
    candidate = Path(__file__).resolve().parent.parent / 'installer' / 'core.py'
    if not candidate.is_file():
        candidate = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'installer' / 'core.py'
    if not candidate.is_file():
        raise SystemExit('找不到卸载组件 installer/core.py')
    spec = importlib.util.spec_from_file_location('installer_core', candidate)
    module = importlib.util.module_from_spec(spec)
    sys.modules['installer_core'] = module
    spec.loader.exec_module(module)
    return module


if __name__=='__main__':
    # --data-dir 必须先解析：后面所有路径都依赖它。
    argv=sys.argv[1:];argv_rest=[];override=None
    index=0
    while index<len(argv):
        if argv[index]=='--data-dir' and index+1<len(argv):
            override=argv[index+1];index+=2;continue
        argv_rest.append(argv[index]);index+=1
    if override:paths.set_override(override)

    if argv_rest[:1]==['--uninstall']:
        _load_installer_core()
        raise SystemExit(_run_uninstall('--silent' in argv_rest))
    if len(argv_rest)>=2 and argv_rest[0]=='--self-check':
        from self_check import _packaged_self_check
        raise SystemExit(_packaged_self_check(Path(argv_rest[1]),Path(argv_rest[2]) if len(argv_rest)>2 else None))
    import webview
    from webview.dom import DOMEventHandler
    ui_check=len(argv_rest)>=2 and argv_rest[0]=='--ui-check'
    # 参数已经从 argv_rest 里解析过，这里必须用它，不能再读 sys.argv 的下标：
    # 带上 --data-dir 之后 sys.argv 的下标会整体偏移。
    check_json=Path(argv_rest[1]) if ui_check else None
    check_clp=Path(argv_rest[2]) if ui_check and len(argv_rest)>2 else None
    paths.ensure()
    library=Library(Path(argv_rest[1]).parent/'ui-check-routes') if ui_check else None
    if library is None:
        library=Library()
        # 旧版遗留的十六进制文件名按内容改成可读名；解不开的原样保留。
        try:library.migrate_readable_names()
        except Exception:pass
    api=Api(library, Prefs(Path(argv_rest[1]).parent/'ui-check-prefs.json') if ui_check else None)
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent));ui=root/'ui'/'index.html'
    if not ui.exists():ui=Path(__file__).parent.parent/'shared'/'ui'/'index.html'
    window=webview.create_window('途记 1.5.1 · NEF GPS Studio',str(ui),js_api=Bridge(api),width=1180,height=860,min_size=(850,680),background_color='#f3f8ff');api.window=window
    def closing():
        if api.job['busy']:api.stop.set();api.job['status']='已请求停止，请等当前照片完成后再关闭。';return False
    window.events.closing+=closing
    def install_native_drop():
        """把 body 的 drop 事件接到 Python，才能拿到被拖文件的真实路径。"""
        try:
            elements=window.dom.get_elements('body')
            if not elements:return
            elements[0].events.drop+=DOMEventHandler(api.on_native_drop)
            api.native_drop=True
            window.evaluate_js('window.nativeDropReady&&window.nativeDropReady(true)')
        except Exception:
            api.native_drop=False
    window.events.loaded+=install_native_drop
    def check_ui():
        import time
        result={}
        try:
            for _ in range(60):
                time.sleep(.5)
                result=window.evaluate_js("({platform:document.body.className,bridge:!!window.pywebview,heading:document.querySelector('#heading')?.textContent,leaflet:!!window.L,ui:{dial:!!document.querySelector('.dial-time'),pill:!!document.querySelector('.nav-pill'),plates:document.querySelectorAll('.sticker-plate').length,steps:document.querySelectorAll('#steps li').length,dropzone:!!document.querySelector('#dropzone'),settingsNav:document.querySelectorAll('nav [data-page=settings]').length,settingsCards:document.querySelectorAll('#settings .setting').length,writtenPanel:!!document.querySelector('#written-panel'),modeSelect:!!document.querySelector('#write-mode'),photoList:!!document.querySelector('#photo-list'),trackPicker:!!document.querySelector('#track-picker'),nativeDrop:!!window.__nativeDropReady,trackMode:!!document.querySelector('#track-mode'),curveNote:!!document.querySelector('#curve-note'),photoMap:!!document.querySelector('#photo-map')}})")
                if result.get('platform')=='windows':break
            result['ok']=bool(result.get('platform')=='windows' and result.get('bridge') and result.get('leaflet')
                              and all(result.get('ui',{}).get(k) for k in ('dial','pill','plates','steps','dropzone','settingsNav','settingsCards','writtenPanel','modeSelect','photoList','trackPicker','nativeDrop','trackMode','curveNote','photoMap')))
            if check_clp is not None and result['ok']:
                id=api.library.import_file(check_clp)
                window.evaluate_js("openRoute("+json.dumps(id)+"); true")
                for _ in range(40):
                    time.sleep(.25)
                    if window.evaluate_js("!!payload && payload.points.length > 0"):break
                window.evaluate_js("node=11;renderTrack();true")
                total=window.evaluate_js("payload.points.length")
                result['reviewNodes']=total
                result['reviewPrefix']=window.evaluate_js("document.querySelector('#node-number').textContent")
                result['ok']=result['ok'] and total>11 and result['reviewPrefix']=='12 / '+str(total)
                api.library.delete(id)
        except Exception as e:result={'ok':False,'error':str(e)}
        # 报告写失败也必须把窗口关掉，否则检查会挂死在那里。
        try:check_json.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        except Exception as e:print('ui-check report failed:',e,file=sys.stderr)
        finally:window.destroy()
    webview.start(check_ui if ui_check else None,gui='edgechromium',private_mode=True)
