package app.nefgpstrack;

import android.location.Location;

/** Keeps one real fix while a single-point capture briefly waits for MSL altitude. */
final class SingleFixBuffer {
    static final long ALTITUDE_WAIT_MS = 10_000L;

    static final class Candidate {
        final Location fix;
        final AltitudeResolver.Reading altitude;
        Candidate(Location fix, AltitudeResolver.Reading altitude) {
            this.fix = new Location(fix);
            this.altitude = altitude;
        }
    }

    private Candidate pending;

    synchronized boolean isEmpty() { return pending == null; }

    synchronized boolean offer(Location fix, AltitudeResolver.Reading altitude, long routeStarted) {
        // A cached GPS point may be fresh (<15 s) but still precede this recording.
        // Such a point cannot finish capture: TrackDb would reject it at save time.
        if (fix.getTime() < routeStarted) return false;
        boolean hasMsl = Double.isFinite(altitude.msl);
        if (pending == null || hasMsl ||
                (!Double.isFinite(pending.altitude.msl) &&
                 fix.getAccuracy() <= pending.fix.getAccuracy())) {
            pending = new Candidate(fix, altitude);
        }
        return hasMsl;
    }

    synchronized Candidate take() {
        Candidate selected = pending;
        pending = null;
        return selected;
    }
}
