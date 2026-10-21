"""第二步：把第一步产出的定位节点变成平滑曲线。

分工（1.4.2 起）：
- 第一步「滤掉 GPS 定位漂移」由手机端在停止记录时完成，结果就是 CLP 里的 points；
- 第二步「插值形成平滑曲线」由电脑端在选中 CLP 时完成，也就是本模块。

手机端导出的 CLP 里没有 curve；文件里若带了 curve 系数（1.4.1 及更早导出），
一律丢弃并按 points 重建——不信任外来系数，只信经过校验的节点。

本模块同时保留第一步的 Python 等价实现 `_fit`，它只用于 smoothing 缺失或无法识别的
旧 CLP：这类文件没有第一步结果，电脑端只能补做。对已经是 robust-stop-v1/v2 的载荷
绝不重复平滑。
"""
import math, statistics
from curve import build_curve
VERSION='robust-stop-v2'
def _solve(a,b):
    n=len(b);l=[[0.,0.,0.] for _ in b]
    for i in range(n):
        for j in range(max(0,i-2),i+1):
            s=a[i][i-j]-sum(l[i][i-k]*l[j][j-k] for k in range(max(0,i-2,j-2),j))
            l[i][i-j]=math.sqrt(max(s,1e-14)) if i==j else s/l[j][0]
    y=[0.]*n;x=[0.]*n
    for i in range(n):y[i]=(b[i]-sum(l[i][i-j]*y[j] for j in range(max(0,i-2),i)))/l[i][0]
    for i in range(n-1,-1,-1):x[i]=(y[i]-sum(l[j][j-i]*x[j] for j in range(i+1,min(n,i+3))))/l[i][0]
    return x
def _fit(p):
    n=len(p)
    if not n:return []
    p=[dict(r) for r in p]
    for i in range(1,n):p[i]['lon']=p[i-1]['lon']+(p[i]['lon']-p[i-1]['lon']+180)%360-180
    lat0=sum(r['lat']/n for r in p);lon0=sum(r['lon']/n for r in p);scale=6371008.8*math.pi/180;sx=scale*max(1e-8,math.cos(math.radians(lat0)))
    xy=[[(r['lon']-lon0)*sx for r in p],[(r['lat']-lat0)*scale for r in p]]
    sig=[max(3,r['hacc'] if r['hacc'] is not None else 50)*(1 if r['provider']=='gps' else 4) for r in p]
    dt=[max(.05,(b['t']-a['t'])/1000) for a,b in zip(p,p[1:])];stop=[False]*(n-1);run=[]
    for i in range(n+1):
        if i<n and p[i]['provider']!='gps':continue
        if i<n and p[i]['speed'] is not None and 0<=p[i]['speed']<=.3:run.append(i)
        else:
            if len(run)>=4:
                a,b=run[0],run[-1];mx=statistics.median(xy[0][k] for k in run);my=statistics.median(xy[1][k] for k in run)
                spread=max(math.hypot(xy[0][k]-mx,xy[1][k]-my) for k in run)
                if p[b]['t']-p[a]['t']>=40000 and spread<=max(50,2*statistics.median(sig[k] for k in run)):
                    for k in range(a,b):stop[k]=True
            run=[]
    def add(h,start,v):
        for j in range(len(v)):
            for k in range(j+1):h[start+j][j-k]+=v[j]*v[k]
    fits=[]
    for axis in range(2):
        x=xy[axis][:]
        for _ in range(60):
            h=[[0.,0.,0.] for _ in p];rhs=[0.]*n
            for i in range(n):
                residual=(x[i]-xy[axis][i])/sig[i];w=1/math.sqrt(1+residual*residual)/(sig[i]*sig[i]);h[i][0]=w+1e-12;rhs[i]=w*xy[axis][i]
            for i in range(1,n-1):
                q=.035*max(1,(dt[i-1]+dt[i])/2);add(h,i-1,[1/dt[i-1]/q,(-1/dt[i-1]-1/dt[i])/q,1/dt[i]/q])
            for i in range(n-1):
                if stop[i]:
                    q=max(.2,.025*dt[i]);add(h,i,[-1/q,1/q])
            nxt=_solve(h,rhs);change=max(abs(a-b) for a,b in zip(nxt,x));x=nxt
            if change<1e-5:break
        fits.append(x)
    return [(lat0+fits[1][i]/scale,lon0+fits[0][i]/sx) for i in range(n)]


def legacy_smooth(payload):
    """第一步的电脑端兜底实现：只给没有第一步结果的旧 CLP 用。"""
    raw=payload.get('rawPoints',payload['points']);corrected=[];start=0
    for i in range(1,len(raw)+1):
        if i==len(raw):
            block=raw[start:i]
            for p,(lat,lon) in zip(block,_fit(block)):
                d=math.hypot((lat-p['lat'])*111195.08,(lon-p['lon'])*111195.08*math.cos(math.radians(p['lat'])))
                corrected.append(dict(p,lat=max(-90,min(90,lat)),lon=(lon+180)%360-180,correctionMeters=d))
            start=i
    return corrected,raw


def build_curves(payload):
    """第二步入口：返回带 curve 的载荷。

    第一步已完成 → 只插值；第一步缺失 → 先补做第一步再插值。
    任何情况下都丢弃文件里带来的 curve 系数。
    """
    base={k:v for k,v in payload.items() if k!='curve'}
    if base.get('smoothing') in (VERSION,'robust-stop-v1') or base.get('mode')=='single':
        points=base['points']
    else:
        points,raw=legacy_smooth(base)
        base=dict(base,rawPoints=raw,smoothing=VERSION)
    points,smoothed=smooth_altitude(points)
    result=dict(base,points=points,curve=build_curve(points))
    if smoothed:result['altitudeSmoothing']=ALT_VERSION
    return result


ALT_VERSION='robust-alt-v1'


def _alt_sigma(y):
    """由二阶差分中位数稳健估计海拔噪声。

    一阶差分里混着真实坡度，拿它当噪声会高估；二阶差分把线性趋势消掉，
    估出来的才是噪声本身（噪声方差 = 二阶差分方差 / 6）。
    """
    if len(y)<3:return 5.0
    d2=[abs(y[i+1]-2*y[i]+y[i-1]) for i in range(1,len(y)-1)]
    median=statistics.median(d2)
    if median<=0:return 5.0
    return max(1.0,min(30.0,1.4826*median/math.sqrt(6)))


def _alt_penalty(h,start,v):
    for j in range(len(v)):
        for k in range(j+1):h[start+j][j-k]+=v[j]*v[k]


def smooth_altitude(points):
    """海拔轴的第一步：与水平轴同源的鲁棒 IRLS，二阶差分做粗糙度惩罚。

    只平滑已知海拔；缺失的一律保持缺失，绝不按邻近值补出来。
    处理不了（已知海拔少于三个）时原样返回。第一步的水平平滑 `_fit` 不在此改动，
    它与 Java 的数值一致性由 qa/test_v120.py 守护。
    """
    known=[i for i,p in enumerate(points) if p.get('alt') is not None]
    if len(known)<3:return list(points),0
    t=[points[i]['t'] for i in known]
    y=[float(points[i]['alt']) for i in known]
    sigma=_alt_sigma(y)
    dt=[max(.05,(b-a)/1000) for a,b in zip(t,t[1:])]
    x=y[:]
    for _ in range(60):
        h=[[0.,0.,0.] for _ in y];rhs=[0.]*len(y)
        for i in range(len(y)):
            residual=(x[i]-y[i])/sigma
            w=1/math.sqrt(1+residual*residual)/(sigma*sigma);h[i][0]=w+1e-12;rhs[i]=w*y[i]
        for i in range(1,len(y)-1):
            q=.05*max(1,(dt[i-1]+dt[i])/2)
            _alt_penalty(h,i-1,[1/dt[i-1]/q,(-1/dt[i-1]-1/dt[i])/q,1/dt[i]/q])
        nxt=_solve(h,rhs);change=max(abs(a-b) for a,b in zip(nxt,x));x=nxt
        if change<1e-4:break
    out=[dict(p) for p in points]
    for position,index in enumerate(known):
        out[index]['alt']=x[position]
    return out,len(known)


# 兼容旧调用名，语义同上。
smooth_payload=build_curves
