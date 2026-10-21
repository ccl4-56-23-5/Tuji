"""Reproduce the documentation diagrams with fictional nodes and the actual curve.py."""
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'sources/NefGpsTrack/1.5.1/windows'))
from curve import build_curve,evaluate

font_path=Path(r'C:\Windows\Fonts\msyh.ttc')
if font_path.exists():
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font_path)).get_name()
else:
    plt.rcParams['font.family']=['Noto Sans CJK SC','DejaVu Sans']
plt.rcParams.update({'font.size':12,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})
out=repo/'docs/images';out.mkdir(exist_ok=True)
blue='#1976d2';gray='#99a6b7';green='#18a57a'
def save(fig,name):
    fig.savefig(out/name,dpi=160,metadata={'Software':'Tuji fictional algorithm illustration'})
    plt.close(fig)

# The y values are an arbitrary synthetic axis, not real geographic observations.
t=np.array([0.,10.,40.]);y=np.array([0.,10.,12.])
points=[dict(t=int(a*1000),lat=float(b),lon=0.,alt=None,hacc=5.) for a,b in zip(t,y)]
c=build_curve(points);query=25.;answer=evaluate(c,query*1000)[0]
assert abs(answer-11.548780487804878)<1e-10
times=np.linspace(0,40,401);values=[evaluate(c,float(v)*1000)[0] for v in times]
fig,ax=plt.subplots(figsize=(10,4.6),layout='constrained')
ax.plot(t,y,'--',color=gray,lw=1.8,label='节点间直接连线')
ax.plot(times,values,color=blue,lw=2.8,label='当前 curve.py 的 PCHIP')
ax.scatter(t,y,c=blue,s=55,zorder=4,label='虚构节点')
ax.scatter([query],[answer],c=green,s=80,zorder=5)
ax.axvline(query,color=green,ls=':',lw=1.3)
ax.annotate('照片时刻 25 秒\nPCHIP = 11.5488\n直线插值 = 11.0000',xy=(query,answer),xytext=(19,4.5),arrowprops=dict(arrowstyle='->',color=green),color='#173b60',fontsize=12)
ax.set(xlabel='合成相对时间（秒）',ylabel='虚构单轴数值（不是实际经纬度）',title='相同节点，不同插值：照片时刻怎样落到曲线上')
ax.grid(alpha=.12);ax.legend(loc='lower right',frameon=False);save(fig,'interpolation-demo.png')

t=[0,20,40,60,80,100];z=[None,100.,None,120.,125.,None]
c=build_curve([dict(t=a*1000,lat=i*.01,lon=0.,alt=b,hacc=5.) for i,(a,b) in enumerate(zip(t,z))])
times=np.linspace(20,80,301);values=[evaluate(c,float(v)*1000)[2] for v in times]
assert evaluate(c,0)[2] is None and evaluate(c,100000)[2] is None
fig,ax=plt.subplots(figsize=(10,4.6),layout='constrained')
ax.axvspan(0,20,color='#edf1f6');ax.axvspan(80,100,color='#edf1f6')
ax.plot(times,values,c=blue,lw=2.8,label='仅用已知海拔节点建立的子曲线')
known=[(a,b) for a,b in zip(t,z) if b is not None]
ax.scatter(*zip(*known),s=65,c=blue,zorder=4,label='已有海拔节点')
for a,b in zip(t,z):
    if b is None:ax.scatter(a,89,facecolors='white',edgecolors=gray,s=60,zorder=4)
ax.annotate('水平节点缺少海拔\n海拔子曲线可从前后已知节点跨过',xy=(40,evaluate(c,40000)[2]),xytext=(24,94),arrowprops=dict(arrowstyle='->',color=green),fontsize=11,color='#173b60')
ax.text(10,119,'范围之外\n保持未知',ha='center',color='#62788e');ax.text(90,108,'范围之外\n保持未知',ha='center',color='#62788e')
ax.text(50,85.5,'空心圆仅标记海拔缺失的时刻，不表示该处海拔数值',ha='center',fontsize=10,color='#62788e')
ax.set(xlim=(-2,102),ylim=(84,130),xticks=t,yticks=[100,110,120],xlabel='合成相对时间（秒）',ylabel='虚构海拔值（米）',title='海拔独立插值：跳过缺失节点，两端不外推')
ax.grid(alpha=.12);ax.legend(loc='upper left',frameon=False,fontsize=10)
save(fig,'altitude-demo.png')
print('Fictional diagrams generated; PCHIP numeric example and altitude limits verified.')
