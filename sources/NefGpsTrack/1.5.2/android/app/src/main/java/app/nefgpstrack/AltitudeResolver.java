package app.nefgpstrack;

import android.content.Context;
import android.location.Location;
import androidx.core.location.LocationCompat;
import androidx.core.location.altitude.AltitudeConverterCompat;

/** Offline WGS84-to-MSL conversion. Never relabel an ellipsoid height as MSL. */
final class AltitudeResolver {
    static final String VERSION = "msl-compat-v1";

    static final class Reading {
        final double msl, ellipsoid, accuracy, verticalAccuracy;
        final double latitude, longitude, horizontalAccuracy;
        final String source, provider;

        Reading(Location fix, String source) {
            msl = LocationCompat.hasMslAltitude(fix)
                    ? finite(LocationCompat.getMslAltitudeMeters(fix)) : Double.NaN;
            ellipsoid = fix.hasAltitude() ? finite(fix.getAltitude()) : Double.NaN;
            accuracy = LocationCompat.hasMslAltitudeAccuracy(fix)
                    ? nonNegative(LocationCompat.getMslAltitudeAccuracyMeters(fix)) : Double.NaN;
            verticalAccuracy = fix.hasVerticalAccuracy()
                    ? nonNegative(fix.getVerticalAccuracyMeters()) : Double.NaN;
            latitude = fix.getLatitude();
            longitude = fix.getLongitude();
            horizontalAccuracy = fix.hasAccuracy() ? nonNegative(fix.getAccuracy()) : Double.NaN;
            provider = fix.getProvider() == null ? "unknown" : fix.getProvider();
            this.source = source;
        }
    }

    /** Called on the location worker: AndroidX may read its bundled geoid assets. */
    static Reading resolve(Context context, Location fix) {
        Location converted = new Location(fix);
        if (hasFiniteMsl(converted)) return new Reading(converted, "provided-msl");
        LocationCompat.removeMslAltitude(converted);
        LocationCompat.removeMslAltitudeAccuracy(converted);
        if (!converted.hasAltitude() || !Double.isFinite(converted.getAltitude())) {
            return new Reading(converted, "unknown");
        }
        try {
            AltitudeConverterCompat.addMslAltitudeToLocation(context, converted);
            if (hasFiniteMsl(converted)) return new Reading(converted, "androidx-msl");
        } catch (Exception unavailable) {
            // Keep the original ellipsoid observation for diagnosis/recovery; alt stays null.
        }
        LocationCompat.removeMslAltitude(converted);
        LocationCompat.removeMslAltitudeAccuracy(converted);
        return new Reading(converted, "conversion-failed");
    }

    static boolean hasFiniteMsl(Location fix) {
        return LocationCompat.hasMslAltitude(fix)
                && Double.isFinite(LocationCompat.getMslAltitudeMeters(fix));
    }

    private static double finite(double value) {
        return Double.isFinite(value) ? value : Double.NaN;
    }

    private static double nonNegative(double value) {
        return Double.isFinite(value) && value >= 0 ? value : Double.NaN;
    }
}
