"""Shape-preserving C1 Hermite curve, parameterized by UTC milliseconds.

四维曲线：时间 t → (纬度, 展开后的经度, 海拔)，三条轴都用同一套保形 Hermite。

海拔轴单独存放为一条子曲线 `alt`，只以海拔已知的结点为节点：这样中间缺失海拔的
时段会被前后已知海拔跨过去插值，而不是整段取不到海拔；两端之外仍然返回 None，
不臆造高度。整条轨迹一个海拔都没有时 `alt` 为 None，海拔恒为 None。

系数是每毫秒的导数。经度先按短路径展开再拟合，输出时归一到 [-180,180)。
"""
import bisect

VERSION = 'pchip-4d-v2'


def slopes(t, y):
    n = len(t)
    m = [None] * n
    start = 0
    while start < n:
        if y[start] is None:
            start += 1
            continue
        end = start + 1
        while end < n and y[end] is not None:
            end += 1
        if end - start == 1:
            m[start] = 0.0
        else:
            h = [t[i+1]-t[i] for i in range(start, end-1)]
            d = [(y[i+1]-y[i])/h[i-start] for i in range(start, end-1)]
            m[start], m[end-1] = d[0], d[-1]
            for i in range(1, len(d)):
                w1, w2 = 2*h[i]+h[i-1], h[i]+2*h[i-1]
                m[start+i] = (w1+w2)/(w1/d[i-1]+w2/d[i]) if d[i-1]*d[i] > 0 else 0.0
            if len(d) > 1:
                for k, a, b, ha, hb in ((start,d[0],d[1],h[0],h[1]),(end-1,d[-1],d[-2],h[-1],h[-2])):
                    v = ((2*ha+hb)*a-ha*b)/(ha+hb)
                    m[k] = 0.0 if v*a <= 0 else (3*a if a*b <= 0 and abs(v)>abs(3*a) else v)
        start = end
    return m


def _axis(times, values):
    """一条独立轴的自描述曲线；values 里不允许有 None。"""
    return dict(times=list(times), values=list(values), slopes=slopes(list(times), list(values)))


def _value(axis, time):
    if not axis:
        return None
    t = axis['times']
    if not t or time < t[0] or time > t[-1]:
        return None
    i = bisect.bisect_left(t, time)
    if i < len(t) and t[i] == time:
        return axis['values'][i]
    a, b = i-1, i
    h = t[b]-t[a]
    u = (time-t[a])/h
    y, m = axis['values'], axis['slopes']
    return (2*u**3-3*u*u+1)*y[a]+(u**3-2*u*u+u)*h*m[a]+(-2*u**3+3*u*u)*y[b]+(u**3-u*u)*h*m[b]


def build_curve(points):
    # Best accuracy wins duplicate times; insertion order never affects a fit.
    unique = {}
    for p in points:
        old = unique.get(p['t'])
        if old is None or (p.get('hacc') if p.get('hacc') is not None else float('inf')) < (old.get('hacc') if old.get('hacc') is not None else float('inf')):
            unique[p['t']] = p
    ps = [unique[t] for t in sorted(unique)]
    t = [p['t'] for p in ps]
    lon = []
    for p in ps:
        lon.append(p['lon'] if not lon else lon[-1]+(p['lon']-lon[-1]+180)%360-180)
    axes = [[p['lat'] for p in ps], lon, [p['alt'] for p in ps]]
    # 海拔子曲线：跳过缺失海拔的结点，让插值跨过这些空档。
    known = [(p['t'], p['alt']) for p in ps if p['alt'] is not None]
    alt = _axis([k[0] for k in known], [k[1] for k in known]) if known else None
    return dict(version=VERSION, times=t, values=axes, slopes=[slopes(t, y) for y in axes], alt=alt)


def evaluate(curve, time):
    t = curve['times']
    if not t or time < t[0] or time > t[-1]:
        return None
    i = bisect.bisect_left(t, time)
    if i < len(t) and t[i] == time:
        lat, lon = curve['values'][0][i], curve['values'][1][i]
        return (lat, (lon+180) % 360-180, _value(curve.get('alt'), time))
    a, b = i-1, i
    h = t[b]-t[a]; u = (time-t[a])/h
    result = []
    for axis in (0, 1):
        y, m = curve['values'][axis], curve['slopes'][axis]
        v = (2*u**3-3*u*u+1)*y[a]+(u**3-2*u*u+u)*h*m[a]+(-2*u**3+3*u*u)*y[b]+(u**3-u*u)*h*m[b]
        result.append((v+180) % 360-180 if axis == 1 else v)
    return (result[0], result[1], _value(curve.get('alt'), time))


def altitude_span(curve):
    """海拔可用的时间范围 (最早已知, 最晚已知)；整条没有海拔数据时返回 None。"""
    alt = curve.get('alt')
    if not alt or not alt['times']:
        return None
    return (alt['times'][0], alt['times'][-1])
