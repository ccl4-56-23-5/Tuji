from pathlib import Path
from zipfile import ZipFile
import hashlib,json
from PyInstaller.archive.readers import CArchiveReader
root=Path(__file__).resolve().parents[1];workspace=root.parents[2];out=workspace/'outputs/NefGpsTrack/1.5.1'
html=(root/'shared/ui/index.html').read_text(encoding='utf8')
with ZipFile(out/'NefGpsTrack-Android-1.5.1.apk') as z:
    for file in (root/'shared/ui').iterdir():assert z.read('assets/ui/'+file.name)==file.read_bytes(),file
    assert '默认平滑' not in z.read('assets/ui/index.html').decode()
    packed=z.read('assets/ui/index.html').decode()
    assert 'dial-time' in packed and '1.5.1' in packed,'APK carries a stale UI build'
exe=CArchiveReader(str(out/'NefGpsTrack-Windows-1.5.1.exe'))
for file in (root/'shared/ui').iterdir():
    names=[x for x in exe.toc if x.replace('\\','/')=='ui/'+file.name];assert len(names)==1,(file,names)
    assert exe.extract(names[0])==file.read_bytes(),file
# 本版新增的界面构件必须真的打进两端包里，避免只改了源码没进产物。
required=('dropzone','written-panel','write-mode','written-rows','track-picker','photo-list','track-mode','curve-note','photo-map-panel','photo-map')
missing=[m for m in required if m not in html or m not in packed]
assert not missing,'packaged UI is missing this version features: '+str(missing)
# 脚本入口：app.js 与两端包内的副本已在上面的逐字节比对中等同，这里核对源码确实带上新入口。
script=(root/'shared/ui/app.js').read_text(encoding='utf8')
required_js=('nativeDropFiles','nativeDropReady','selectedTracks','renderTrackPicker','renderPhotoList',
             'applyTrackMode','mergeTracks','curvePosition','renderPhotoMap','pickSpot','renderPhotoRows')
missing_js=[m for m in required_js if m not in script]
assert not missing_js,'app.js is missing this version features: '+str(missing_js)
# 四维曲线：海拔子曲线必须在，且不能再有「任一端无海拔就整段返回 None」的旧写法。
curve_src=(root/'windows/curve.py').read_text(encoding='utf8')
assert "VERSION = 'pchip-4d-v2'" in curve_src,'windows curve is not the 4D build'
assert "'alt'" in curve_src and 'altitude_span' in curve_src,'windows curve has no altitude sub-curve'
tool_src=(root/'windows/exiftool_io.py').read_text(encoding='utf8')
assert 'has_existing_position' in tool_src,'windows writer cannot tell an empty GPS IFD from a real position'
# 手机端不再做第二步：不能残留曲线实现，也不能再往载荷里塞 curve。
assert not (root/'android/app/src/main/java/app/nefgpstrack/TrackCurve.java').exists(),\
    'android still ships TrackCurve.java'
# 1.5.1：多格式支持必须同时落在后端与界面里，且夹具随源码归档
_tool=(root/'windows/exiftool_io.py').read_text(encoding='utf8')
for _s in ('".nef"', '".dng"', '".jpg"', '".jpeg"', '".png"', '".heic"', '".heif"'):
    assert _s in _tool, 'exiftool_io is missing '+_s
assert 'file_type_ok' in _tool and 'SUPPORTED_SUFFIXES' in _tool
_ui=(root/'shared/ui/app.js').read_text(encoding='utf8')
assert 'PHOTO_RE' in _ui and 'heic' in _ui and 'dng' in _ui, 'ui does not accept the new formats'
_fixtures=sorted(p.name for p in (root/'qa/formats').iterdir())
assert len(_fixtures)>=4, 'format fixtures are missing: '+str(_fixtures)
_trackdb=(root/'android/app/src/main/java/app/nefgpstrack/TrackDb.java').read_text(encoding='utf8')
assert 'curve' not in _trackdb.lower(),'android TrackDb still mentions curve'
# 1.5.1：安装器必须真的把主程序当作载荷带在身上，且载荷与独立主程序逐字节一致。
setup_name='NefGpsTrack-Setup-1.5.1.exe'
setup=out/setup_name
assert setup.is_file(),'installer was not built: '+setup_name
archive=CArchiveReader(str(setup))
payload_names=[x for x in archive.toc if x.replace('\\','/') in ('payload/途记.exe','payload/途记')]
assert len(payload_names)==1,'installer payload entry missing: '+str(payload_names)
payload_bytes=archive.extract(payload_names[0])
app_bytes=(out/'NefGpsTrack-Windows-1.5.1.exe').read_bytes()
assert hashlib.sha256(payload_bytes).hexdigest()==hashlib.sha256(app_bytes).hexdigest(),\
    'installer payload differs from the standalone app'
# 安装器界面与主程序界面都要在包里
setup_ui=[x for x in archive.toc if x.replace('\\','/').startswith('ui/')]
assert setup_ui,'installer UI files missing'
# 数据层：路径库必须落在数据目录下，且不再读写 %LOCALAPPDATA%
_paths=(root/'windows/paths.py').read_text(encoding='utf8')
assert "ROUTES_DIR_NAME = \"路径库\"" in _paths and 'APPDATA_DIR_NAME = "程序数据"' in _paths,\
    'data layout constants changed unexpectedly'
_library=(root/'windows/library.py').read_text(encoding='utf8')
# 真正的不变量是「路径库不再自己去读环境变量」，环境查找统一归 paths.py。
# 文档字符串里提到 %LOCALAPPDATA% 是说明历史，不算违规。
assert 'environ' not in _library,'library reads environment paths directly'
assert 'paths.routes_dir()' in _library,'library does not default to the data folder'
assert 'migrate_readable_names' in _library,'legacy hex names are never turned readable'
report={'version':'1.5.1','androidSharedAssetsMatch':True,'windowsSharedAssetsMatch':True,
        'installerPayloadMatchesApp':True,
        'installerName':setup_name,
        'newUiMarkersPacked':sorted(m for m in ('dial-time','nav-pill','date-tile','detail-grid','dropzone','written-panel','write-mode','track-picker','photo-list','track-mode','curve-note','photo-map-panel') if m in html),
        'requiredFeatureMarkers':list(required),
        'requiredScriptMarkers':list(required_js),
        'phoneDoesOnlyStageOne':True,
        'dataLivesUnderInstallPath':True,
        'photoFormats':['nef','dng','jpg','jpeg','png','heic','heif'],
        'formatFixtures':sorted(p.name for p in (root/'qa/formats').iterdir()),
        'noLogoInHtmlOrCss': 'brand.png' not in html and 'brand.png' not in (root/'shared/ui/style.css').read_text(encoding='utf-8-sig'),
        'files':[{'name':f.name,'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in out.iterdir() if f.suffix in ('.exe','.apk')]}
(out/'package-verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
(out/'SHA256.txt').write_text('\n'.join(f"{x['sha256']}  {x['name']}" for x in report['files'])+'\n',encoding='utf8')
print(json.dumps(report,indent=2))
