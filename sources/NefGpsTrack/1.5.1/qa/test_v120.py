"""Behavioral regression checks; optionally writes only temporary NEF copies."""
import sys, unittest, tempfile, shutil, hashlib, json, subprocess, os
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'windows'))
from curve import build_curve, evaluate, slopes
from clp_codec import TrackPoint, encrypt_clp, decrypt_clp, FIXED_KEY, ClpError
from time_match import build_track_index, match_track, capture_utc_ms
from batch import Options, prepare_plan, execute_plan
from exiftool_io import ExifTool

def point(t,lat=30,lon=100,alt=10,hacc=5):
    return TrackPoint(t,lat,lon,alt,hacc,None,None,'gps')

class Regression(unittest.TestCase):
    def test_long_gap_and_no_extrapolation(self):
        ps=[point(0),point(600000,31,101,30),point(1800000,32,102,35)]
        idx=build_track_index(ps)
        m=match_track(idx,300000)
        self.assertEqual(m.method,'curve-long-gap');self.assertEqual(m.point.t,300000)
        self.assertTrue(30<m.point.lat<31);self.assertTrue(10<m.point.alt<30)
        self.assertIsNone(match_track(idx,-1));self.assertIsNone(match_track(idx,1800001))
    def test_single_is_explicit(self):
        p=point(600000)
        self.assertIsNone(match_track([p],0))
        m=match_track(build_track_index([p],mode='single'),-86400000)
        self.assertEqual(m.point.t,-86400000);self.assertEqual(m.point.alt,p.alt)
        self.assertEqual(m.source_before_ms,p.t);self.assertEqual(m.method,'single')
    def test_duplicate_best_and_unknown_altitude(self):
        idx=build_track_index([point(1000),point(0,hacc=30),point(0,lat=31,hacc=5),point(2000,alt=None)])
        self.assertEqual(len(idx.points),3);self.assertEqual(idx.points[0].lat,31)
        self.assertIsNone(match_track(idx,1500).point.alt)
    def test_monotonic_bounded_c1(self):
        c=build_curve([asdict(point(t,lat=y,alt=y)) for t,y in [(0,0),(1000,1),(4000,1),(10000,5)]])
        values=[evaluate(c,t)[0] for t in range(0,10001,10)]
        self.assertTrue(all(a<=b+1e-12 for a,b in zip(values,values[1:])))
        for t in (1000,4000):
            eps=.01;y=evaluate(c,t)[0]
            self.assertAlmostEqual((y-evaluate(c,t-eps)[0])/eps,(evaluate(c,t+eps)[0]-y)/eps,places=6)
    def test_dateline(self):
        m=match_track([point(0,lon=179),point(10000,lon=-179)],5000)
        self.assertAlmostEqual(abs(m.point.lon),180)
    def test_utc_day_boundary_subsecond_correction(self):
        meta={'ExifIFD:DateTimeOriginal':'2026:09:27 00:00:00','ExifIFD:SubSecTimeOriginal':'123','ExifIFD:OffsetTimeOriginal':'+08:00'}
        t,offset=capture_utc_ms(meta,'-05:00',2)
        from time_match import utc_text
        self.assertEqual(utc_text(t),'2026-09-26T16:00:02.123Z');self.assertEqual(offset,'+08:00')
    def test_protocol_modes(self):
        data=dict(schema='nef-gps-track/1',createdUtcMs=1,mode='single',points=[asdict(point(1))])
        self.assertEqual(decrypt_clp(encrypt_clp(data,FIXED_KEY),FIXED_KEY).mode,'single')
        with self.assertRaises(ClpError):encrypt_clp(dict(data,points=[]),FIXED_KEY)
    def test_stage_split_phone_ships_nodes_only(self):
        """手机端只做第一步：CLP 里没有 curve；第二步由电脑端按节点重建。"""
        from smoothing import build_curves
        java=(ROOT/'android/app/src/main/java/app/nefgpstrack/TrackDb.java').read_text(encoding='utf8')
        self.assertNotIn('curve(',java)
        self.assertNotIn('"curve"',java)
        self.assertFalse((ROOT/'android/app/src/main/java/app/nefgpstrack/TrackCurve.java').exists(),
                         '手机端不应再保留第二步实现')
        raw=[dict(t=0,lat=30.0,lon=100.0,alt=None,hacc=10.0,speed=None,bearing=None,provider='gps'),
             dict(t=1000,lat=30.001,lon=100.0,alt=None,hacc=10.0,speed=None,bearing=None,provider='gps')]
        phone=dict(schema='nef-gps-track/1',createdUtcMs=1,smoothing='robust-stop-v2',mode='track',
                   points=[dict(p,correctionMeters=1.0) for p in raw],rawPoints=raw)
        self.assertNotIn('curve',phone)
        built=build_curves(phone)
        self.assertEqual(built['curve']['version'],'pchip-4d-v2')
        self.assertEqual(len(built['curve']['times']),2)
        # 旧文件里的 curve 系数一律丢弃重建，不信任外来数据
        legacy=dict(phone,curve=dict(version='bogus',times=[0],values=[[0],[0],[0]],slopes=[[0],[0],[0]]))
        rebuilt=build_curves(legacy)
        self.assertEqual(rebuilt['curve']['version'],'pchip-4d-v2')
        self.assertEqual(len(rebuilt['curve']['times']),2)
        # 无 curve 的手机端导出仍能通过协议校验
        self.assertEqual(len(decrypt_clp(encrypt_clp(phone,FIXED_KEY),FIXED_KEY).points),2)
    def test_existing_position_gate(self):
        """只按经纬度海拔判定：空 GPS IFD 不该拦住补录。"""
        from exiftool_io import ExifTool
        empty={'File:FileType':'NEF','GPS:GPSVersionID':'2 3 0 0','GPS:GPSDateStamp':'2026:10:03'}
        self.assertTrue(ExifTool.has_existing_gps(empty))
        self.assertFalse(ExifTool.has_existing_position(empty),'空 GPS IFD 被判成了已有定位')
        self.assertTrue(ExifTool.has_existing_position(dict(empty,**{'GPS:GPSLatitude':36.05})))
        self.assertTrue(ExifTool.has_existing_position(dict(empty,**{'GPS:GPSLongitude':103.85})))
        self.assertTrue(ExifTool.has_existing_position(dict(empty,**{'GPS:GPSAltitude':1500.0})))
        self.assertFalse(ExifTool.has_existing_position({'GPS:GPSLatitude':'   '}))
        self.assertFalse(ExifTool.has_existing_position({}))
    def test_altitude_axis_is_smoothed_and_spans_gaps(self):
        """四维平滑：海拔也被滤过，且中间缺失海拔的时段仍能在曲线上取到合理海拔。"""
        import random, statistics
        from smoothing import smooth_altitude
        from curve import altitude_span, VERSION as CURVE_VERSION
        self.assertEqual(CURVE_VERSION,'pchip-4d-v2')
        random.seed(11)
        # 平路 → 上升 → 下降，分两处转折但整体连续
        truth=[]
        for i in range(60):
            if i<20:truth.append(100.0)
            elif i<40:truth.append(100.0+(i-20)*8.0)
            else:truth.append(252.0-(i-40)*5.0)
        noisy=[v+random.gauss(0,4) for v in truth]
        noisy[15]+=55; noisy[45]-=50
        pts=[dict(t=i*10000,lat=30.0+i*1e-6,lon=100.0+i*1e-6,alt=noisy[i],hacc=8.0,
                  speed=None,bearing=None,provider='gps') for i in range(60)]
        out,count=smooth_altitude(pts)
        self.assertEqual(count,60)
        smoothed=[p['alt'] for p in out]
        raw_err=statistics.pstdev([a-b for a,b in zip(noisy,truth)])
        smooth_err=statistics.pstdev([a-b for a,b in zip(smoothed,truth)])
        self.assertLess(smooth_err,raw_err*0.6,'海拔平滑没有降低残差')
        self.assertLess(max(abs(a-b) for a,b in zip(smoothed,truth)),20.0,'海拔尖峰没有被压低')
        self.assertAlmostEqual(smoothed[0],truth[0],delta=4)
        self.assertAlmostEqual(max(smoothed),max(truth),delta=6)
        self.assertAlmostEqual(smoothed[-1],truth[-1],delta=8)
        # 挖掉头尾与中段的海拔：中段仍应取到海拔，已知范围之外仍为 None
        holed=[dict(p) for p in out]
        for i in list(range(0,6))+list(range(25,35))+list(range(54,60)):holed[i]['alt']=None
        curve=build_curve(holed)
        span=altitude_span(curve)
        self.assertIsNotNone(span)
        inside=evaluate(curve,30*10000)
        self.assertIsNotNone(inside[2],'缺失海拔的时段取不到海拔')
        low,high=min(smoothed[24],smoothed[35]),max(smoothed[24],smoothed[35])
        self.assertTrue(low-30<=inside[2]<=high+30,f'跨空档插值的海拔不合理：{inside[2]}')
        self.assertIsNone(evaluate(curve,5*10000)[2],'首个已知海拔之前仍给出了海拔')
        self.assertIsNone(evaluate(curve,54*10000)[2],'末个已知海拔之后仍给出了海拔')
        self.assertIsNone(evaluate(curve,-1))
        self.assertIsNone(evaluate(curve,60*10000))
        # 整条没有海拔时经纬度仍可用，海拔恒为 None
        bare=build_curve([dict(p,alt=None) for p in out])
        self.assertIsNone(altitude_span(bare))
        value=evaluate(bare,30*10000)
        self.assertIsNotNone(value[0]);self.assertIsNone(value[2])
        # 已知海拔不足三个时不做平滑，原样返回
        few,kept=smooth_altitude([dict(pts[0]),dict(pts[1])])
        self.assertEqual(kept,0)
        self.assertEqual(few[0]['alt'],pts[0]['alt'])
    def test_merge_sources_orders_and_excludes_single(self):
        from batch import merge_sources
        from clp_codec import Track
        a=Track(1,(point(0,30.0),point(1000,30.001)))
        b=Track(1,(point(5000,30.01),point(6000,30.011)))
        lone=Track(1,(point(500,40.0),),mode='single')
        merged=merge_sources([(Path('b.clp'),'B',b),(Path('a.clp'),'A',a)])
        self.assertEqual(merged.index.times,(0,1000,5000,6000))
        self.assertEqual(merged.index.mode,'track')
        self.assertIn('2 条轨迹',merged.label)
        with_single=merge_sources([(Path('a.clp'),'A',a),(Path('s.clp'),'S',lone)])
        self.assertEqual(with_single.index.times,(0,1000))
        self.assertIn('已排除 1 条单点补录',with_single.label)
        with self.assertRaises(ValueError):merge_sources([(Path('s.clp'),'S',lone)])
        # 同一时刻重叠时保留精度更好的点
        better=Track(1,(point(1000,30.5,hacc=3),))
        overlap=merge_sources([(Path('a.clp'),'A',a),(Path('c.clp'),'C',better)])
        self.assertEqual(overlap.index.times,(0,1000))
        self.assertEqual(overlap.index.points[1].lat,30.5)
    def test_merge_gap_stays_a_long_gap(self):
        """两段之间的大空档沿用现有规则标记为长间隔估算，不引入新语义。"""
        from batch import merge_sources
        from clp_codec import Track
        a=Track(1,(point(0,30.0),point(1000,30.001)))
        b=Track(1,(point(600000,31.0),point(601000,31.001)))
        merged=merge_sources([(Path('a.clp'),'A',a),(Path('b.clp'),'B',b)])
        m=match_track(merged.index,300000)
        self.assertEqual(m.method,'curve-long-gap')
        self.assertIsNone(match_track(merged.index,-1))
        self.assertIsNone(match_track(merged.index,601001))
    def test_android_v2_migration_preserves_rows(self):
        import sqlite3,re
        source=(ROOT/'android/app/src/main/java/app/nefgpstrack/TrackDb.java').read_text(encoding='utf8')
        sql=re.search(r'if\(old==2\)d.execSQL\("([^"]+)"\)',source).group(1)
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE routes(id INTEGER PRIMARY KEY,started INTEGER NOT NULL,ended INTEGER,state TEXT NOT NULL,payload TEXT)')
        db.execute("INSERT INTO routes VALUES(1,10,20,'saved','original-payload')")
        before=db.execute('SELECT * FROM routes').fetchone();db.execute(sql)
        after=db.execute('SELECT * FROM routes').fetchone()
        self.assertEqual(before,after[:-1]);self.assertEqual(after[-1],'track');db.close()
    def test_whole_route_horizontal_java_parity(self):
        from smoothing import _fit
        jdk=Path(r'D:\Codex\改软件\tools\jdk-17.0.10.7-hotspot\bin')
        ps=[point(0,30,179.99),point(30000,30.0001,179.991),point(600000,30.002,-179.99),point(630000,30.003,-179.989)]
        rows=[[p.t/1000,p.lat,p.lon,p.hacc,-1,1] for p in ps]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'FitCheck.java'
            literal='{'+','.join('{'+','.join(str(x) for x in row)+'}' for row in rows)+'}'
            source.write_text('import app.nefgpstrack.TrackSmoother; public class FitCheck {public static void main(String[] a){double[][] p='+literal+';for(double[] r:TrackSmoother.smooth(p))System.out.println(r[0]+","+r[1]);}}')
            subprocess.run([str(jdk/'javac.exe'),'-d',tmp,str(ROOT/'android/app/src/main/java/app/nefgpstrack/TrackSmoother.java'),str(source)],check=True,capture_output=True)
            result=subprocess.run([str(jdk/'java.exe'),'-cp',tmp,'FitCheck'],check=True,capture_output=True,text=True)
            for row,(lat,lon) in zip(result.stdout.splitlines(),_fit([asdict(p) for p in ps])):
                a,b=map(float,row.split(','));self.assertAlmostEqual(a,lat,places=8);self.assertAlmostEqual(b,(lon+180)%360-180,places=8)
    @unittest.skipUnless(os.environ.get('TUJI_SAMPLE'),'set TUJI_SAMPLE for real NEF-copy checks')
    def test_nef_single_and_long_gap_readback(self):
        sample=Path(os.environ['TUJI_SAMPLE']);original=hashlib.sha256(sample.read_bytes()).hexdigest()
        exif=ExifTool();meta=exif.metadata(sample);t,_=capture_utc_ms(meta,'+08:00',0)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photos=root/'photos';photos.mkdir();shutil.copy2(sample,photos/sample.name)
            for mode,ps in [('single',[point(t+86400000,alt=-12)]),('track',[point(t-600000,alt=10),point(t+600000,lat=31,alt=40)])]:
                clp=root/(mode+'.clp');clp.write_bytes(encrypt_clp(dict(schema='nef-gps-track/1',createdUtcMs=t,mode=mode,points=[asdict(p) for p in ps]),FIXED_KEY))
                plan=prepare_plan(Options((clp,),photos,(),root/('out-'+mode),'+08:00',0,True),FIXED_KEY,exif)
                self.assertEqual(plan.rows[0].status,'ready',plan.rows[0].reason)
                rows=execute_plan(plan,exif);self.assertEqual(rows[0].result,'written',rows[0].detail)
                self.assertEqual(plan.rows[0].match.point.t,t)
                self.assertIsNotNone(rows[0].latitude)
                self.assertIsNotNone(rows[0].longitude)
                self.assertEqual(rows[0].altitude,plan.rows[0].match.point.alt)
                exif.verify_gps(rows[0].destination,plan.rows[0].match.point)
                written=exif.metadata(rows[0].destination)
                for k in ('ExifIFD:DateTimeOriginal','ExifIFD:SubSecTimeOriginal','ExifIFD:OffsetTimeOriginal'):
                    self.assertEqual(written.get(k),meta.get(k))
            self.assertFalse(list(root.rglob('*.csv')),'写入过程不应生成表格文件')
            self.assertEqual(hashlib.sha256((photos/sample.name).read_bytes()).hexdigest(),original)
        self.assertEqual(hashlib.sha256(sample.read_bytes()).hexdigest(),original)
    # ---------------- 1.5.1 数据层 ----------------
    def test_data_root_follows_install_path(self):
        """1.5.0 起数据在安装路径下的 data\\，不再写 %LOCALAPPDATA%\\NefGpsTrack。"""
        import paths
        if os.environ.get('NEFGPSTRACK_DATA'):self.skipTest('环境变量已覆盖数据根，跳过默认路径断言')
        paths.set_override(None)
        self.assertEqual(paths.data_root(),paths.install_root()/'data')
        self.assertEqual(paths.routes_dir().name,'路径库')
        self.assertEqual(paths.appdata_dir().name,'程序数据')
        self.assertEqual(paths.settings_file(),paths.appdata_dir()/'settings.json')
        # 显式覆盖优先，且不产生任何目录
        with tempfile.TemporaryDirectory() as tmp:
            paths.set_override(tmp)
            self.assertEqual(paths.data_root(),Path(tmp))
            self.assertEqual(paths.routes_dir(),Path(tmp)/'路径库')
            paths.set_override(None)
    def test_readable_route_names_are_unique_and_descriptive(self):
        from library import readable_stem, LEGACY_STEM
        payload=dict(mode='track',createdUtcMs=0,points=[dict(t=1790221525010)]*3)
        stem=readable_stem(payload)
        self.assertRegex(stem,r'^\d{4}-\d{2}-\d{2}_\d{4}_连续_3点$')
        self.assertEqual(readable_stem(payload,taken={stem}),stem+'_2')
        self.assertEqual(readable_stem(payload,taken={stem,stem+'_2'}),stem+'_3')
        self.assertIn('单点',readable_stem(dict(payload,mode='single')))
        # 旧版的十六进制名要被认出来，可读名不能被误判
        self.assertTrue(LEGACY_STEM.match('a'*32));self.assertIsNone(LEGACY_STEM.match(stem))
    def test_route_identifier_cannot_escape_the_library(self):
        from library import Library, safe_stem
        for bad in ('../x','a/b','a\\b','..','','   ','a:b','a*b','a?b','a"b','a<b','a>b','a|b'):
            with self.assertRaises(ValueError):
                safe_stem(bad)
        with tempfile.TemporaryDirectory() as tmp:
            lib=Library(Path(tmp)/'路径库')
            for bad in ('../evil','a/b','..\\evil','..'):
                with self.assertRaises(ValueError):
                    lib.path(bad)
            good=lib.path('2026-09-24_1355_连续_115点')
            self.assertEqual(good.parent,lib.root.resolve())
    def test_library_import_lands_in_the_data_dir_with_a_readable_name(self):
        from library import Library
        with tempfile.TemporaryDirectory() as tmp:
            lib=Library(Path(tmp)/'路径库')
            payload=dict(schema='nef-gps-track/1',createdUtcMs=1,smoothing='robust-stop-v2',mode='track',
                         points=[dict(t=1790221525010,lat=30.0,lon=100.0,alt=None,hacc=8.0,
                                      speed=None,bearing=None,provider='gps',correctionMeters=1.0)])
            stem=lib.import_bytes('拖入.clp',encrypt_clp(payload,FIXED_KEY))
            self.assertIn('连续',stem)
            self.assertTrue((lib.root/f'{stem}.clp').is_file())
            listed=lib.list()
            self.assertEqual(len(listed),1);self.assertEqual(listed[0]['id'],stem)
            self.assertEqual(listed[0]['name'],stem)
            # 再导入一条同期轨迹：文件名必须自动区分
            again=lib.import_bytes('再来一条.clp',encrypt_clp(payload,FIXED_KEY))
            self.assertNotEqual(again,stem)
    def test_legacy_hex_filenames_are_renamed_on_startup(self):
        from library import Library
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'路径库';root.mkdir(parents=True)
            payload=dict(schema='nef-gps-track/1',createdUtcMs=1,smoothing='robust-stop-v2',mode='track',
                         points=[dict(t=1790221525010,lat=30.0,lon=100.0,alt=None,hacc=8.0,
                                      speed=None,bearing=None,provider='gps',correctionMeters=1.0)])
            legacy=root/(('a'*32)+'.clp')
            legacy.write_bytes(encrypt_clp(payload,FIXED_KEY))
            # 十六进制名但内容坏了：认得出是旧名，但解不开，必须原样留着
            broken=root/(('b'*32)+'.clp')
            broken.write_bytes(b'garbage')
            (root/'not-a-clp.clp').write_bytes(b'garbage')
            lib=Library(root)
            result=lib.migrate_readable_names()
            self.assertEqual(result['renamed'],1)
            self.assertEqual(result['kept'],1)
            self.assertFalse(legacy.exists(),'旧十六进制文件名应已改名')
            self.assertTrue(broken.exists(),'解不开的旧名文件必须原样保留')
            names=sorted(p.name for p in root.glob('*.clp'))
            self.assertEqual(len(names),3)
            self.assertTrue(any('连续' in n for n in names))
            self.assertIn('not-a-clp.clp',names,'不匹配旧名格式的文件不该被碰')
            # 幂等
            self.assertEqual(lib.migrate_readable_names()['renamed'],0)

if __name__=='__main__':unittest.main(verbosity=2)
