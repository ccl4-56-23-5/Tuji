import json
from pathlib import Path
from exiftool_io import ExifTool
def _packaged_self_check(report: Path, sample: Path | None) -> int:
    """A noninteractive smoke check for the final one-file EXE."""
    try:
        from clp_codec import decrypt_clp, encrypt_clp, FIXED_KEY

        exif = ExifTool()
        payload = {
            "schema": "nef-gps-track/1", "createdUtcMs": 0,
            "points": [{"t": 0, "lat": 0.0, "lon": 0.0, "alt": None,
                        "hacc": 1.0, "speed": None, "bearing": None, "provider": None}],
        }
        if len(decrypt_clp(encrypt_clp(payload, FIXED_KEY), FIXED_KEY).points) != 1:
            raise RuntimeError("CLP encryption self-check failed")
        result = {"ok": True, "exiftool": exif.version(), "crypto": "CLP1 roundtrip"}
        if sample is not None:
            meta = exif.metadata(sample)
            result["sampleType"] = meta.get("File:FileType")
            result["sampleHasGps"] = exif.has_existing_gps(meta)
            import tempfile, shutil, hashlib
            from batch import Options, prepare_plan, execute_plan
            from time_match import capture_utc_ms
            original = hashlib.sha256(sample.read_bytes()).hexdigest()
            capture, _ = capture_utc_ms(meta, "+08:00", 0)
            with tempfile.TemporaryDirectory(prefix="tuji-self-check-") as tmp:
                root=Path(tmp); photos=root/"photos"; photos.mkdir()
                shutil.copy2(sample, photos/sample.name)
                p=dict(payload['points'][0],t=capture+86400000,lat=30.,lon=100.,alt=-12.)
                checks=[]
                for mode,points in [('single',[p]),('track',[dict(p,t=capture-600000),dict(p,t=capture+600000,lat=31.,alt=20.)])]:
                    clp=root/(mode+'.clp')
                    clp.write_bytes(encrypt_clp(dict(payload,mode=mode,points=points),FIXED_KEY))
                    plan=prepare_plan(Options((clp,),photos,(),root/mode,'+08:00',0,True),FIXED_KEY,exif)
                    rows=execute_plan(plan,exif)
                    if len(rows)!=1 or rows[0].result!='written':
                        raise RuntimeError(str(rows))
                    if plan.rows[0].match.point.t!=capture:
                        raise RuntimeError('GPS timestamp differs from exposure')
                    if rows[0].latitude is None or rows[0].longitude is None or rows[0].altitude is None:
                        raise RuntimeError('written coordinates not returned')
                    checks.append(mode+' NEF copy/readback')
                # 多轨迹择优：两条轨迹只有一条覆盖拍摄时刻，且文件清单优先于目录
                wide=root/'wide.clp'
                wide.write_bytes(encrypt_clp(dict(payload,mode='track',points=[dict(p,t=capture-300000),dict(p,t=capture+300000,lat=31.,alt=20.)]),FIXED_KEY))
                far=root/'far.clp'
                far.write_bytes(encrypt_clp(dict(payload,mode='track',points=[dict(p,t=capture+7200000),dict(p,t=capture+7260000,lat=35.,alt=30.)]),FIXED_KEY))
                single_clp=root/'lone.clp'
                single_clp.write_bytes(encrypt_clp(dict(payload,mode='single',points=[dict(p,t=capture+3600000,lat=40.,alt=5.)]),FIXED_KEY))
                multi_root=root/'multi';multi_root.mkdir()
                multi_photo=multi_root/sample.name
                shutil.copy2(sample,multi_photo)
                multi_plan=prepare_plan(Options((far,wide),None,(multi_photo,),root/'multi-a','+08:00',0,True),FIXED_KEY,exif,
                                        labels={wide.stem:'近轨迹',far.stem:'远轨迹'})
                if multi_plan.rows[0].status!='ready' or multi_plan.rows[0].track_label!='近轨迹':
                    raise RuntimeError('multi-track pick failed: '+str(multi_plan.rows[0]))
                checks.append('multi-track picks the covering track')
                single_plan=prepare_plan(Options((single_clp,wide),None,(multi_photo,),root/'multi-b','+08:00',0,True),FIXED_KEY,exif,
                                         labels={single_clp.stem:'单点',wide.stem:'近轨迹'})
                if single_plan.rows[0].track_label!='近轨迹':
                    raise RuntimeError('single point outranked a covering track: '+str(single_plan.rows[0]))
                checks.append('covering track outranks single point')
                # 第二步在电脑端：合并模式把两条轨迹串成一条曲线
                merge_a=root/'merge-a.clp'
                merge_a.write_bytes(encrypt_clp(dict(payload,mode='track',points=[dict(p,t=capture-300000),dict(p,t=capture+300000,lat=31.,alt=20.)]),FIXED_KEY))
                merge_b=root/'merge-b.clp'
                merge_b.write_bytes(encrypt_clp(dict(payload,mode='track',points=[dict(p,t=capture+3600000),dict(p,t=capture+3900000,lat=32.,alt=25.)]),FIXED_KEY))
                merged=prepare_plan(Options((merge_b,merge_a),None,(multi_photo,),root/'merge-out','+08:00',0,True,False,True),
                                    FIXED_KEY,exif,labels={merge_a.stem:'甲',merge_b.stem:'乙'})
                if merged.track_count!=1 or not merged.rows[0].track_label.startswith('合并的 2 条轨迹'):
                    raise RuntimeError('merge mode did not fold into one curve: '+str(merged.rows[0]))
                if merged.rows[0].status!='ready':
                    raise RuntimeError('merged curve did not cover the exposure: '+str(merged.rows[0]))
                checks.append('two tracks merged into one curve')
                # 就地改写：只改本次临时目录里的副本，并确认替换后确实读得回坐标
                inplace_root=root/'inplace';inplace_root.mkdir()
                inplace_photo=inplace_root/sample.name
                shutil.copy2(sample,inplace_photo)
                before_inplace=hashlib.sha256(inplace_photo.read_bytes()).hexdigest()
                inplace_clp=root/'inplace.clp'
                inplace_clp.write_bytes(encrypt_clp(dict(payload,mode='single',points=[p]),FIXED_KEY))
                inplace_plan=prepare_plan(Options((inplace_clp,),None,(inplace_photo,),None,'+08:00',0,True,True),FIXED_KEY,exif)
                inplace_rows=execute_plan(inplace_plan,exif)
                if len(inplace_rows)!=1 or inplace_rows[0].result!='written':
                    raise RuntimeError('in-place rewrite failed: '+str(inplace_rows))
                if hashlib.sha256(inplace_photo.read_bytes()).hexdigest()==before_inplace:
                    raise RuntimeError('in-place rewrite did not change the file')
                checks.append('in-place NEF rewrite/readback')
                # 只有空 GPS IFD（无经纬度海拔）的照片不该被拦住，而且要拿到四维曲线的海拔
                stub_root=root/'gps-stub';stub_root.mkdir()
                stub=stub_root/sample.name
                shutil.copy2(sample,stub)
                exif._run(["-overwrite_original","-P","-GPS:all=",
                           "-GPS:GPSVersionID=2 3 0 0","-GPS:GPSDateStamp=2026:10:03",str(stub)],timeout=180)
                if exif.has_existing_position(exif.metadata(stub)):
                    raise RuntimeError('empty GPS IFD counted as an existing position')
                stub_plan=prepare_plan(Options((root/'track.clp',),stub_root,(),root/'stub-out','+08:00',0,False),FIXED_KEY,exif)
                if stub_plan.rows[0].status!='ready':
                    raise RuntimeError('empty GPS IFD blocked the write: '+stub_plan.rows[0].reason)
                stub_rows=execute_plan(stub_plan,exif)
                if stub_rows[0].result!='written':
                    raise RuntimeError('stub write failed: '+stub_rows[0].detail)
                if stub_rows[0].latitude is None or stub_rows[0].altitude is None:
                    raise RuntimeError('4D curve did not supply latitude and altitude')
                checks.append('empty GPS IFD is writable')
                checks.append('4D curve supplies an altitude')
                # 1.5.1 数据层：路径库必须落在数据目录的「路径库」里，文件名必须可读
                from paths import data_root, routes_dir
                from library import Library
                probe_lib=Library()
                if probe_lib.root!=routes_dir():
                    raise RuntimeError('library is not using the data folder: '+str(probe_lib.root))
                if routes_dir().parent!=data_root():
                    raise RuntimeError('routes folder is not inside the data root')
                probe_payload=dict(schema='nef-gps-track/1',createdUtcMs=1,smoothing='robust-stop-v2',
                                   mode='track',points=[dict(t=capture,lat=30.0,lon=100.0,alt=1200.0,
                                                             hacc=8.0,speed=None,bearing=None,provider='gps')])
                probe_stem=probe_lib.import_bytes('自检.clp',encrypt_clp(probe_payload,FIXED_KEY))
                if not (probe_lib.root/(probe_stem+'.clp')).is_file():
                    raise RuntimeError('import did not land in the data folder')
                if '连续' not in probe_stem or '1点' not in probe_stem:
                    raise RuntimeError('route name is not readable: '+probe_stem)
                probe_lib.delete(probe_stem)
                checks.append('data folder and readable route name')
                if list(root.rglob('*.csv')):
                    raise RuntimeError('table file produced')
                checks.append('no table file produced')
                if hashlib.sha256((photos/sample.name).read_bytes()).hexdigest()!=original:
                    raise RuntimeError('Input copy changed')
            if hashlib.sha256(sample.read_bytes()).hexdigest()!=original:
                raise RuntimeError('Original sample changed')
            result.update(checks=checks, originalSha256=original)
        code = 0
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        code = 1
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


