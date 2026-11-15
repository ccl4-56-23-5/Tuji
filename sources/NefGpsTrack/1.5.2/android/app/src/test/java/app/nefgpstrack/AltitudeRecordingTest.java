package app.nefgpstrack;

import static org.junit.Assert.*;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.location.Location;
import androidx.core.location.LocationCompat;
import androidx.core.location.altitude.AltitudeConverterCompat;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Actual Android Location/SQLite/AndroidX resource tests on both sides of API 34. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = {26, 34})
public class AltitudeRecordingTest {
    private Context context;
    private TrackDb db;
    private long route, time;

    @Before public void create() {
        context = RuntimeEnvironment.getApplication();
        context.deleteDatabase("track.db");
        db = new TrackDb(context);
        route = db.begin();
        time = System.currentTimeMillis() + 1000;
    }

    @After public void close() {
        if (db != null) db.close();
        context.deleteDatabase("track.db");
    }

    private Location fix(String provider, float horizontal, double msl, float accuracy) {
        Location point = new Location(provider);
        point.setTime(time);
        point.setLatitude(0);
        point.setLongitude(0);
        point.setAccuracy(horizontal);
        if (Double.isFinite(msl)) LocationCompat.setMslAltitudeMeters(point, msl);
        if (Float.isFinite(accuracy)) LocationCompat.setMslAltitudeAccuracyMeters(point, accuracy);
        return point;
    }

    private boolean add(Location fix) {
        return db.add(fix, AltitudeResolver.resolve(context, fix));
    }

    private JSONObject point() throws Exception {
        return db.payload(route).getJSONArray("rawPoints").getJSONObject(0);
    }

    @Test public void olderAndroidGetsOfflineMslConversion() throws Exception {
        Location fix = fix("gps", 4, Double.NaN, Float.NaN);
        fix.setAltitude(100);
        fix.setVerticalAccuracyMeters(5);
        // The API <34 implementation uses Room, which correctly rejects a main
        // thread query. Match TrackService's location-worker execution here.
        ExecutorService worker = Executors.newSingleThreadExecutor();
        AltitudeResolver.Reading result;
        try {
            result = worker.submit(() -> {
                // Keep original exceptions if a real resource/converter fails;
                // the production resolver deliberately preserves a null fallback.
                AltitudeConverterCompat.addMslAltitudeToLocation(context, new Location(fix));
                return AltitudeResolver.resolve(context, fix);
            }).get(30, TimeUnit.SECONDS);
        } finally {
            worker.shutdownNow();
        }
        assertEquals("androidx-msl", result.source);
        assertEquals(100, result.ellipsoid, 0);
        // EGM geoid separation at (0,0) is approximately 17 m, not zero.
        assertEquals(83, result.msl, 2);
        assertTrue(Double.isFinite(result.accuracy));
        assertTrue(result.accuracy >= result.verticalAccuracy);
        assertFalse("Do not mutate the provider's object", LocationCompat.hasMslAltitude(fix));
    }

    @Test public void suppliedMslIsNotConvertedTwice() {
        Location fix = fix("gps", 4, 42, 3);
        fix.setAltitude(100);
        AltitudeResolver.Reading result = AltitudeResolver.resolve(context, fix);
        assertEquals("provided-msl", result.source);
        assertEquals(42, result.msl, 0);
        assertEquals(100, result.ellipsoid, 0);
    }

    @Test public void absentHeightStaysUnknownAndNeverBecomesZero() throws Exception {
        assertTrue(add(fix("network", 20, Double.NaN, Float.NaN)));
        assertTrue(point().isNull("alt"));
        assertTrue(point().isNull("ellipsoidAlt"));
        assertEquals("unknown", point().getString("altSource"));
    }

    @Test public void invalidConversionKeepsRawEllipsoidButNoMsl() {
        Location fix = fix("gps", 5, Double.NaN, Float.NaN);
        fix.setLatitude(91); // A converter rejection, independent of service validation.
        fix.setAltitude(123);
        AltitudeResolver.Reading result = AltitudeResolver.resolve(context, fix);
        assertEquals("conversion-failed", result.source);
        assertTrue(Double.isNaN(result.msl));
        assertEquals(123, result.ellipsoid, 0);
    }

    @Test public void betterHorizontalFixCannotEraseExistingMsl() throws Exception {
        assertTrue(add(fix("gps", 10, 72, 4)));
        Location network = fix("network", 3, Double.NaN, Float.NaN);
        network.setLatitude(0.00001);
        assertTrue(add(network));
        JSONObject point = point();
        assertEquals(72, point.getDouble("alt"), 0);
        assertEquals(3, point.getDouble("hacc"), 0);
        assertEquals("network", point.getString("provider"));
        assertEquals("gps", point.getString("altProvider"));
        assertEquals(0, point.getDouble("altLat"), 0);
        assertEquals(1, db.count());
    }

    @Test public void equalOrWorseHorizontalFixMaySupplyMissingMsl() throws Exception {
        assertTrue(add(fix("network", 3, Double.NaN, Float.NaN)));
        assertTrue(add(fix("gps", 8, 65, 4)));
        assertEquals(65, point().getDouble("alt"), 0);
        assertEquals(3, point().getDouble("hacc"), 0);
        assertEquals("network", point().getString("provider"));
        assertEquals("gps", point().getString("altProvider"));
        assertEquals(1, db.count());
    }

    @Test public void verticalAccuracyChoosesMslIndependently() throws Exception {
        assertTrue(add(fix("gps", 4, 65, 9)));
        assertTrue(add(fix("gps", 8, 70, 2)));
        assertEquals(70, point().getDouble("alt"), 0);
        assertEquals(4, point().getDouble("hacc"), 0);
        assertFalse(add(fix("gps", 9, 80, 20)));
        assertEquals(70, point().getDouble("alt"), 0);
    }

    @Test public void unknownVerticalAccuracyUsesOriginalAltitudeHorizontalAccuracy() throws Exception {
        assertTrue(add(fix("gps", 20, 65, Float.NaN)));
        assertTrue(add(fix("network", 2, Double.NaN, Float.NaN)));
        assertTrue(add(fix("gps", 10, 70, Float.NaN)));
        assertEquals(70, point().getDouble("alt"), 0);
        assertEquals(2, point().getDouble("hacc"), 0);
        assertEquals(10, point().getDouble("altHacc"), 0);
    }

    @Test public void spatiallyIncompatibleProvidersDoNotShareMsl() throws Exception {
        assertTrue(add(fix("network", 3, Double.NaN, Float.NaN)));
        Location far = fix("gps", 8, 500, 1);
        far.setLatitude(1);
        assertFalse(add(far));
        assertTrue(point().isNull("alt"));
        Location betterFar = fix("gps", 1, 500, 1);
        betterFar.setLatitude(1);
        assertTrue(add(betterFar));
        assertEquals(500, point().getDouble("alt"), 0);
        assertEquals(1, point().getDouble("lat"), 0);
    }

    @Test public void repeatedHorizontalReplacementCannotDragHeightAway() throws Exception {
        assertTrue(add(fix("gps", 100, 72, 4)));
        Location first = fix("network", 80, Double.NaN, Float.NaN);
        first.setLatitude(0.0008); // 89 m from altitude observation.
        assertTrue(add(first));
        assertEquals(72, point().getDouble("alt"), 0);
        Location second = fix("network", 60, Double.NaN, Float.NaN);
        second.setLatitude(0.0016); // Another 89 m, but 178 m from height source.
        assertTrue(add(second));
        assertTrue(point().isNull("alt"));
    }

    @Test public void differentTimesNeverCarryForwardHeight() throws Exception {
        assertTrue(add(fix("gps", 5, 65, 2)));
        time += 30000;
        assertTrue(add(fix("network", 5, Double.NaN, Float.NaN)));
        assertEquals(2, db.count());
        assertTrue(db.payload(route).getJSONArray("rawPoints").getJSONObject(1).isNull("alt"));
    }

    @Test public void stoppedRouteCacheAndRawHeightsRemainStable() throws Exception {
        assertTrue(add(fix("gps", 4, 42, 2)));
        db.finish();
        JSONObject saved = db.payload(route);
        assertEquals("msl-compat-v1", saved.getString("altitudeAcquisition"));
        assertEquals(42, saved.getJSONArray("points").getJSONObject(0).getDouble("alt"), 0);
        assertEquals(42, saved.getJSONArray("rawPoints").getJSONObject(0).getDouble("alt"), 0);
        assertEquals(saved.toString(), db.payload(route).toString());
    }

    @Test public void sameTimestampCannotMovePointToAnotherRoute() throws Exception {
        assertTrue(add(fix("gps", 5, 42, 2)));
        db.finish();
        db.begin();
        assertFalse(add(fix("gps", 1, 52, 1)));
        assertEquals(0, db.count());
        assertEquals(42, db.payload(route).getJSONArray("rawPoints").getJSONObject(0).getDouble("alt"), 0);
    }

    @Test public void versionThreeUpgradePreservesCachedPayloadAndMsl() throws Exception {
        db.close(); db = null;
        context.deleteDatabase("track.db");
        String cached = "{\"schema\":\"nef-gps-track/1\",\"points\":[{\"t\":123,\"lat\":0,\"lon\":0,\"alt\":45}],\"rawPoints\":[]}";
        try (SQLiteDatabase old = context.openOrCreateDatabase("track.db", 0, null)) {
            old.execSQL("CREATE TABLE points(t INTEGER PRIMARY KEY,lat REAL NOT NULL,lon REAL NOT NULL,alt REAL,hacc REAL NOT NULL,speed REAL,bearing REAL,provider TEXT NOT NULL,route INTEGER NOT NULL DEFAULT 0)");
            old.execSQL("CREATE TABLE routes(id INTEGER PRIMARY KEY AUTOINCREMENT,started INTEGER NOT NULL,ended INTEGER,state TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'track',payload TEXT)");
            old.execSQL("CREATE INDEX points_route ON points(route,t)");
            old.execSQL("INSERT INTO routes VALUES(1,100,200,'saved','track',?)", new Object[]{cached});
            old.execSQL("INSERT INTO points(t,lat,lon,alt,hacc,provider,route) VALUES(123,0,0,45,5,'gps',1)");
            old.setVersion(3);
        }
        db = new TrackDb(context);
        assertEquals(4, db.getReadableDatabase().getVersion());
        assertEquals(new JSONObject(cached).toString(), db.payload(1).toString());
        try (Cursor row = db.getReadableDatabase().rawQuery("SELECT alt,altSource,ellipsoidAlt,altProvider FROM points", null)) {
            assertTrue(row.moveToFirst());
            assertEquals(45, row.getDouble(0), 0);
            assertEquals("legacy-msl", row.getString(1));
            assertTrue(row.isNull(2));
            assertEquals("gps", row.getString(3));
        }
    }

    @Test public void singlePointWaitsForAltitudeThenKeepsOneRealFix() {
        SingleFixBuffer buffer = new SingleFixBuffer();
        Location horizontal = fix("gps", 4, Double.NaN, Float.NaN);
        assertFalse(buffer.offer(horizontal, AltitudeResolver.resolve(context, horizontal), db.activeStarted()));
        time += 2000;
        Location full = fix("gps", 5, 42, 2);
        assertTrue(buffer.offer(full, AltitudeResolver.resolve(context, full), db.activeStarted()));
        SingleFixBuffer.Candidate saved = buffer.take();
        assertEquals(full.getTime(), saved.fix.getTime());
        assertEquals(42, saved.altitude.msl, 0);
        assertTrue(buffer.isEmpty());
        assertNull(buffer.take());
    }

    @Test public void singlePointGraceExpiryRetainsBestHorizontalWithoutInventingAltitude() {
        SingleFixBuffer buffer = new SingleFixBuffer();
        Location best = fix("gps", 3, Double.NaN, Float.NaN);
        assertFalse(buffer.offer(best, AltitudeResolver.resolve(context, best), db.activeStarted()));
        time += 2000;
        Location worse = fix("gps", 15, Double.NaN, Float.NaN);
        assertFalse(buffer.offer(worse, AltitudeResolver.resolve(context, worse), db.activeStarted()));
        SingleFixBuffer.Candidate saved = buffer.take();
        assertEquals(best.getTime(), saved.fix.getTime());
        assertEquals(3, saved.fix.getAccuracy(), 0);
        assertTrue(Double.isNaN(saved.altitude.msl));
        assertEquals(10_000L, SingleFixBuffer.ALTITUDE_WAIT_MS);
    }

    @Test public void freshButPreStartGpsCannotPrematurelyFinishSingleCapture() {
        SingleFixBuffer buffer = new SingleFixBuffer();
        long started = db.activeStarted();
        Location cached = fix("gps", 3, 42, 2);
        cached.setTime(started - 1000);
        assertFalse(buffer.offer(cached, AltitudeResolver.resolve(context, cached), started));
        assertTrue(buffer.isEmpty());
        assertNull(buffer.take());
        Location current = fix("gps", 5, 43, 3);
        current.setTime(started);
        assertTrue(buffer.offer(current, AltitudeResolver.resolve(context, current), started));
        SingleFixBuffer.Candidate saved = buffer.take();
        assertTrue(db.add(saved.fix, saved.altitude));
        assertEquals(1, db.count());
    }
}
