package app.nefgpstrack;

import java.util.*;

/** Robust weighted position fit + acceleration regularization + stationary velocity penalty.
 * Banded Cholesky and IRLS: O(n) memory/time per iteration. No network or Android dependency. */
public final class TrackSmoother {
    public static final String VERSION="robust-stop-v2";
    public static double[][] smooth(double[][] p) {
        double[][] out=new double[p.length][2];
        int a=0;
        for(int i=1;i<=p.length;i++) if(i==p.length) {
            double[][] block=Arrays.copyOfRange(p,a,i), fit=fit(block);
            for(int k=0;k<fit.length;k++) out[a+k]=fit[k];a=i;
        }
        return out;
    }
    // rows: seconds, latitude, longitude, accuracy, speed (-1 unknown), GPS (1/0)
    private static double[][] fit(double[][] p) {
        int n=p.length;double[][] out=new double[n][2];if(n==0)return out;
        double[][] copy=new double[n][];for(int i=0;i<n;i++){copy[i]=p[i].clone();if(i>0){double delta=p[i][2]-copy[i-1][2];copy[i][2]=copy[i-1][2]+((delta+180)%360+360)%360-180;}}p=copy;
        double lat0=0,lon0=0;for(double[] r:p){lat0+=r[1]/n;lon0+=r[2]/n;}
        double scale=6371008.8*Math.PI/180, sx=scale*Math.max(1e-8,Math.cos(lat0*Math.PI/180));
        double[][] xy=new double[2][n];double[] sig=new double[n],dt=new double[Math.max(0,n-1)];
        for(int i=0;i<n;i++){xy[0][i]=(p[i][2]-lon0)*sx;xy[1][i]=(p[i][1]-lat0)*scale;sig[i]=Math.max(3,p[i][3])*(p[i][5]==1?1:4);if(i>0)dt[i-1]=Math.max(.05,p[i][0]-p[i-1][0]);}
        boolean[] stop=new boolean[Math.max(0,n-1)];List<Integer> run=new ArrayList<>();
        for(int i=0;i<=n;i++){if(i<n&&p[i][5]!=1)continue;
            if(i<n&&p[i][4]>=0&&p[i][4]<=.3)run.add(i);
            else {if(run.size()>=4){int a=run.get(0),b=run.get(run.size()-1);double[] xs=new double[run.size()],ys=xs.clone(),ss=xs.clone();for(int j=0;j<run.size();j++){int k=run.get(j);xs[j]=xy[0][k];ys[j]=xy[1][k];ss[j]=sig[k];}double mx=median(xs),my=median(ys),spread=0;for(int k:run)spread=Math.max(spread,Math.hypot(xy[0][k]-mx,xy[1][k]-my));if(p[b][0]-p[a][0]>=40&&spread<=Math.max(50,2*median(ss)))for(int k=a;k<b;k++)stop[k]=true;}run.clear();}
        }
        double[][] fit=new double[2][];
        for(int axis=0;axis<2;axis++){
            double[] x=xy[axis].clone();
            for(int iter=0;iter<60;iter++){
                double[][] h=new double[n][3];double[] rhs=new double[n];
                for(int i=0;i<n;i++){double residual=(x[i]-xy[axis][i])/sig[i];double w=1/Math.sqrt(1+residual*residual)/(sig[i]*sig[i]);h[i][0]=w+1e-12;rhs[i]=w*xy[axis][i];}
                for(int i=1;i<n-1;i++){double q=.035*Math.max(1,(dt[i-1]+dt[i])/2);add(h,i-1,new double[]{1/dt[i-1]/q,(-1/dt[i-1]-1/dt[i])/q,1/dt[i]/q});}
                for(int i=0;i<n-1;i++)if(stop[i]){double q=Math.max(.2,.025*dt[i]);add(h,i,new double[]{-1/q,1/q});}
                double[] next=solve(h,rhs);double change=0;for(int i=0;i<n;i++)change=Math.max(change,Math.abs(next[i]-x[i]));x=next;if(change<1e-5)break;
            }fit[axis]=x;
        }
        for(int i=0;i<n;i++){out[i][0]=Math.max(-90,Math.min(90,lat0+fit[1][i]/scale));double lon=lon0+fit[0][i]/sx;out[i][1]=((lon+180)%360+360)%360-180;}return out;
    }
    private static double median(double[] v){Arrays.sort(v);return v.length%2==1?v[v.length/2]:(v[v.length/2-1]+v[v.length/2])/2;}
    private static void add(double[][] h,int start,double[] v){for(int j=0;j<v.length;j++)for(int k=0;k<=j;k++)h[start+j][j-k]+=v[j]*v[k];}
    private static double[] solve(double[][] a,double[] b){
        int n=b.length;double[][] l=new double[n][3];
        for(int i=0;i<n;i++)for(int j=Math.max(0,i-2);j<=i;j++){double sum=a[i][i-j];for(int k=Math.max(0,Math.max(i-2,j-2));k<j;k++)sum-=l[i][i-k]*l[j][j-k];l[i][i-j]=i==j?Math.sqrt(Math.max(sum,1e-14)):sum/l[j][0];}
        double[] y=new double[n],x=new double[n];for(int i=0;i<n;i++){double v=b[i];for(int j=Math.max(0,i-2);j<i;j++)v-=l[i][i-j]*y[j];y[i]=v/l[i][0];}
        for(int i=n-1;i>=0;i--){double v=y[i];for(int j=i+1;j<=Math.min(n-1,i+2);j++)v-=l[j][j-i]*x[j];x[i]=v/l[i][0];}return x;
    }
}
