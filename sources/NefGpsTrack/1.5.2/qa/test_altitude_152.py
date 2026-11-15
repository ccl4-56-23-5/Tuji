"""Synthetic regression coverage for MSL retention and bounded reconstruction."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from dataclasses import asdict, replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'windows'))
from altitude import deduplicate_points
from clp_codec import Track, TrackPoint, _parse_payload, ClpError
from curve import build_curve, evaluate
from time_match import build_track_index, match_track
from smoothing import build_curves, smooth_altitude
from batch import merge_sources, describe_match, Options, Plan, PlanRow, AuditRow


def point(time, alt=None, **extra):
    return replace(TrackPoint(time, 30.0, 100.0, alt, 5.0, None, None, 'gps'), **extra)


def payload(points):
    return dict(schema='nef-gps-track/1', createdUtcMs=0, mode='track',
                smoothing='robust-stop-v2', points=[asdict(p) for p in points])


class Altitude152(unittest.TestCase):
    def test_exact_missing_node_uses_same_height_as_neighboring_times(self):
        index=build_track_index([point(0,100),point(30_000),point(60_000,160)])
        match=match_track(index,30_000)
        self.assertEqual(match.method,'exact')
        self.assertAlmostEqual(match.point.alt,130)
        self.assertEqual(match.point.altSource,'interpolated-msl')
        self.assertEqual((match.point.altSourceBeforeMs,match.point.altSourceAfterMs),(0,60_000))
        self.assertIn('海拔估算',describe_match(match,1))
        self.assertAlmostEqual(match_track(index,29_999).point.alt,129.999)

    def test_short_gap_boundary_and_unknown_ends(self):
        index=build_track_index([point(0),point(1000,-20),point(61_000),point(121_000,0),point(122_000)])
        self.assertAlmostEqual(match_track(index,61_000).point.alt,-10)
        self.assertIsNone(match_track(index,500).point.alt)
        self.assertIsNone(match_track(index,121_500).point.alt)
        too_long=build_track_index([point(0,0),point(60_000),point(120_001,100)])
        self.assertIsNone(match_track(too_long,60_000).point.alt)
        self.assertEqual(match_track(too_long,120_001).point.alt,100)

    def test_all_missing_and_one_observation_do_not_invent_height(self):
        self.assertIsNone(match_track([point(0),point(60_000)],30_000).point.alt)
        index=build_track_index([point(0),point(30_000,12),point(60_000)])
        self.assertIsNone(match_track(index,10_000).point.alt)
        self.assertEqual(match_track(index,30_000).point.alt,12)
        self.assertIsNone(match_track(index,50_000).point.alt)

    def test_simultaneous_height_survives_better_horizontal_fix(self):
        a=point(0,100,hacc=15,ellipsoidAlt=130,verticalAccuracy=3,altAccuracy=4,altSource='provided-msl')
        b=point(0,None,hacc=3,lon=100.00001,provider='network')
        before=[asdict(a),asdict(b)]
        snapshot=copy.deepcopy(before)
        forward=deduplicate_points(before)
        self.assertEqual(forward,deduplicate_points(list(reversed(before))))
        self.assertEqual(forward[0]['alt'],100)
        self.assertEqual(forward[0]['lon'],b.lon)
        self.assertEqual(forward[0]['altProvider'],'gps')
        self.assertEqual(forward[0]['altHacc'],15)
        self.assertEqual(forward[0]['ellipsoidAlt'],130)
        self.assertEqual(forward[0]['verticalAccuracy'],3)
        self.assertEqual(before,snapshot)

    def test_incompatible_same_time_height_is_not_transferred(self):
        index=build_track_index([point(0,100,hacc=15,lat=31),point(0,None,hacc=3)])
        self.assertIsNone(index.points[0].alt)
        # The original altitude position remains authoritative after a prior merge.
        far_source=point(0,100,hacc=4,altLat=31,altLon=100,altHacc=10)
        self.assertIsNone(build_track_index([point(0,None,hacc=3),far_source]).points[0].alt)

    def test_vertical_accuracy_and_msl_basis(self):
        index=build_track_index([point(0,100,altAccuracy=20),point(0,104,hacc=8,altAccuracy=2)])
        self.assertEqual(index.points[0].alt,104)
        only_ellipsoid=point(0,None,ellipsoidAlt=150,verticalAccuracy=3,altSource='conversion-failed')
        parsed=_parse_payload(json.dumps(payload([only_ellipsoid])).encode()).points[0]
        self.assertIsNone(parsed.alt)
        self.assertEqual(parsed.ellipsoidAlt,150)
        self.assertIsNone(match_track(build_track_index([parsed],mode='single'),1000).point.alt)

    def test_optional_metadata_validation_and_legacy_compatibility(self):
        data=payload([point(0,0)])
        for name in ('ellipsoidAlt','verticalAccuracy','altAccuracy','altSource','altProvider',
                     'altHacc','altLat','altLon','altSourceBeforeMs','altSourceAfterMs'):
            data['points'][0].pop(name)
        self.assertEqual(_parse_payload(json.dumps(data).encode()).points[0].alt,0)
        for key,value in [('altAccuracy',-1),('ellipsoidAlt',True),('altLat',91),('altSource',4),('altOriginal','invalid')]:
            invalid=copy.deepcopy(data);invalid['points'][0][key]=value
            with self.assertRaises(ClpError):_parse_payload(json.dumps(invalid).encode())

    def test_rebuilding_does_not_repeatedly_smooth_or_edit_raw(self):
        data=payload([point(i*10_000,alt) for i,alt in enumerate([100,104,None,98,103,100])])
        data['rawPoints']=copy.deepcopy(data['points'])
        original=copy.deepcopy(data)
        first=build_curves(data)
        second=build_curves(first)
        self.assertEqual(data,original)
        self.assertEqual(first['rawPoints'],original['rawPoints'])
        self.assertEqual(first['points'],second['points'])
        self.assertIsNone(first['points'][2]['altOriginal'])
        self.assertEqual(first['points'][2]['altSource'],'interpolated-msl')
        self.assertIsNotNone(first['points'][2]['alt'])
        self.assertEqual(first['curve'],second['curve'])

    def test_rebuilding_without_raw_uses_saved_original_heights(self):
        data=payload([point(i*10_000,alt) for i,alt in enumerate([100,104,None,98,103,100])])
        first=build_curves(data);second=build_curves(first)
        self.assertEqual(first['points'],second['points'])
        self.assertEqual(first['curve'],second['curve'])

    def test_old_smoothed_file_without_raw_is_not_smoothed_again(self):
        data=payload([point(i*10_000,alt) for i,alt in enumerate([100,104,None,98,103,100])])
        data['altitudeSmoothing']='robust-alt-v1'
        first=build_curves(data);second=build_curves(first)
        self.assertEqual(first['points'][1]['alt'],104)
        self.assertTrue(first['altitudeInputUnavailable'])
        self.assertEqual(first['points'],second['points'])

    def test_long_outage_does_not_pull_neighboring_slopes_or_smoothing(self):
        left=[asdict(point(i*10_000,alt)) for i,alt in enumerate([1,4,2])]
        right=[asdict(point(600_000+i*10_000,alt)) for i,alt in enumerate([900,850,890])]
        smoothed,_=smooth_altitude(left+right)
        self.assertEqual(smoothed[:3],smooth_altitude(left)[0])
        self.assertEqual(smoothed[3:],smooth_altitude(right)[0])
        together=build_curve(left+right);alone=build_curve(left)
        self.assertEqual(evaluate(together,5000),evaluate(alone,5000))
        self.assertIsNone(evaluate(together,300_000)[2])

    def test_merge_path_uses_independent_height_selection(self):
        a=Track(0,(point(0,100,hacc=8),point(60_000,160)))
        b=Track(0,(point(0,None,hacc=3),point(30_000)))
        merged=merge_sources([(Path('a.clp'),'A',a),(Path('b.clp'),'B',b)])
        self.assertEqual(merged.index.points[0].alt,100)
        self.assertAlmostEqual(match_track(merged.index,30_000).point.alt,130)

    def test_estimated_provenance_reaches_preview_and_write_payloads(self):
        import app
        match=match_track([point(0,100),point(30_000),point(60_000,160)],30_000)
        options=Options((Path('route.clp'),),None,(Path('photo.jpg'),),Path('out'),'+00:00',0)
        row=PlanRow(Path('photo.jpg'),Path('photo.jpg'),1,1,30_000,'+00:00',match,'ready',
                    describe_match(match,1),1,track_label='synthetic')
        plan=Plan(options,1,(row,))
        api=app.Api(library=object(),prefs=object())
        with patch.object(app,'prepare_plan',return_value=plan),patch.object(app,'ExifTool',return_value=object()):
            api._preview(options,{})
        self.assertTrue(api.job['ready'])
        self.assertEqual(api.job['points'][0]['altSource'],'interpolated-msl')
        self.assertIn('海拔估算',api.job['rows'][0][3])
        audit=AuditRow(row,'written','GPS IFD 已读回验证 · 海拔估算',Path('out/photo.jpg'),30,100,130)
        with patch.object(app,'execute_plan',return_value=(audit,)),patch.object(app,'ExifTool',return_value=object()):
            api._write()
        self.assertEqual(api.job['written'][0]['altSource'],'interpolated-msl')
        self.assertEqual(api.job['written'][0]['alt'],130)

    def test_duplicate_low_quality_height_cannot_pollute_before_deduplication(self):
        for bad in (-10000,10000):
            data=payload([point(0,100,altAccuracy=3),point(0,bad,hacc=80,altAccuracy=100),
                          point(10_000,100,altAccuracy=3),point(20_000,100,altAccuracy=3)])
            data['rawPoints']=copy.deepcopy(data['points'])
            original=copy.deepcopy(data)
            first=build_curves(data);second=build_curves(first)
            self.assertEqual(first['rawPoints'],original['rawPoints'])
            self.assertEqual(len(first['points']),4)
            self.assertEqual([p['altOriginal'] for p in first['points']],[100,bad,100,100])
            self.assertEqual(first['points'],second['points'])
            self.assertEqual(data,original)
            # Exercise the persisted CLP -> dataclass -> photo index path too.
            index=build_track_index(_parse_payload(json.dumps(first).encode()).points)
            for time in (0,5000,10_000,20_000):
                self.assertAlmostEqual(match_track(index,time).point.alt,100,places=5)

    def test_equal_quality_duplicate_choice_stays_stable_after_smoothing(self):
        data=payload([point(0,100,altAccuracy=3),point(0,101,altAccuracy=3),
                      point(10_000,120,altAccuracy=3),point(20_000,120,altAccuracy=3)])
        first=build_curves(data)
        index=build_track_index(_parse_payload(json.dumps(first).encode()).points)
        self.assertAlmostEqual(match_track(index,0).point.alt,evaluate(first['curve'],0)[2])
        self.assertEqual(first['points'],build_curves(first)['points'])


if __name__=='__main__':
    unittest.main(verbosity=2)
