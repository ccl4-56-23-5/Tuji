"""MSL observation selection shared by curve building and photo matching."""
import math

MAX_ALTITUDE_GAP_MS = 120_000
ALT_FIELDS = ('alt', 'ellipsoidAlt', 'verticalAccuracy', 'altAccuracy', 'altSource', 'altProvider',
              'altSourceBeforeMs', 'altSourceAfterMs', 'altHacc', 'altLat', 'altLon')


def _accuracy(value):
    return value if value is not None and math.isfinite(value) and value >= 0 else math.inf


def position_compatible(a, b):
    """Only combine simultaneous observations whose horizontal error areas overlap."""
    if a['t'] != b['t']:
        return False
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2-lat1
    dlon = math.radians((b['lon']-a['lon']+180) % 360-180)
    hav = math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    distance = 12742017.6*math.asin(math.sqrt(min(1.0, hav)))
    limit = max(10.0, min(100.0, _accuracy(a.get('hacc'))+_accuracy(b.get('hacc'))))
    return distance <= limit


def deduplicate_points(points, *, include_sources=False):
    """Choose horizontal position and compatible MSL height independently; do not mutate inputs."""
    groups = {}
    for point in points:
        groups.setdefault(point['t'], []).append(point)
    output = []
    for time in sorted(groups):
        candidates = groups[time]
        horizontal = min(candidates, key=lambda p: (
            _accuracy(p.get('hacc')), p['lat'], p['lon'], p.get('provider') or ''))
        selected = dict(horizontal)
        height = None
        heights = [p for p in candidates if p.get('alt') is not None and
                   math.isfinite(p['alt']) and (p is horizontal or position_compatible(horizontal, dict(p,
                       lat=p.get('altLat') if p.get('altLat') is not None else p['lat'],
                       lon=p.get('altLon') if p.get('altLon') is not None else p['lon'],
                       hacc=p.get('altHacc') if p.get('altHacc') is not None else p.get('hacc'))))]
        if heights:
            height = min(heights, key=lambda p: (
                p.get('altSource') == 'interpolated-msl', _accuracy(p.get('altAccuracy')),
                _accuracy(p.get('altHacc') if p.get('altHacc') is not None else p.get('hacc')),
                p.get('altProvider') or p.get('provider') or '',
                p.get('altLat') if p.get('altLat') is not None else p['lat'],
                p.get('altLon') if p.get('altLon') is not None else p['lon']))
            for field in ALT_FIELDS:
                selected[field] = height.get(field)
            selected['altSource'] = height.get('altSource') or 'legacy-msl'
            selected['altProvider'] = height.get('altProvider') or height.get('provider')
            for field, fallback in (('altHacc', 'hacc'), ('altLat', 'lat'), ('altLon', 'lon')):
                selected[field] = height.get(field) if height.get(field) is not None else height.get(fallback)
        output.append((selected, height) if include_sources else selected)
    return output
