package app.nefgpstrack;
import android.content.*;
import android.database.*;
import android.database.sqlite.*;
import android.location.Location;
import android.os.Build;
import org.json.*;

final class TrackDb extends SQLiteOpenHelper {
    TrackDb(Context c){super(c,"track.db",null,3);setWriteAheadLoggingEnabled(true);}
    public void onCreate(SQLiteDatabase d){d.execSQL("CREATE TABLE points(t INTEGER PRIMARY KEY,lat REAL NOT NULL,lon REAL NOT NULL,alt REAL,hacc REAL NOT NULL,speed REAL,bearing REAL,provider TEXT NOT NULL,route INTEGER NOT NULL DEFAULT 0)");routes(d);}
    private void routes(SQLiteDatabase d){d.execSQL("CREATE TABLE routes(id INTEGER PRIMARY KEY AUTOINCREMENT,started INTEGER NOT NULL,ended INTEGER,state TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'track',payload TEXT)");d.execSQL("CREATE INDEX points_route ON points(route,t)");}
    public void onUpgrade(SQLiteDatabase d,int old,int next){if(old==1){d.execSQL("ALTER TABLE points ADD COLUMN route INTEGER NOT NULL DEFAULT 0");routes(d);d.execSQL("INSERT INTO routes(started,ended,state) SELECT MIN(t),MAX(t),'saved' FROM points HAVING COUNT(*)>0");d.execSQL("UPDATE points SET route=(SELECT MAX(id) FROM routes)");}if(old==2)d.execSQL("ALTER TABLE routes ADD COLUMN kind TEXT NOT NULL DEFAULT 'track'");}
    synchronized long active(){try(Cursor c=getReadableDatabase().rawQuery("SELECT id FROM routes WHERE state='recording' ORDER BY id DESC LIMIT 1",null)){return c.moveToFirst()?c.getLong(0):0;}}
    synchronized long begin(){return begin(false);}
    synchronized long begin(boolean single){long id=active();if(id!=0)return id;ContentValues v=new ContentValues();v.put("started",System.currentTimeMillis());v.put("state","recording");v.put("kind",single?"single":"track");return getWritableDatabase().insertOrThrow("routes",null,v);}
    synchronized void finish() throws Exception {long id=active();if(id==0)return;ContentValues v=new ContentValues();v.put("ended",System.currentTimeMillis());v.put("state","saved");getWritableDatabase().update("routes",v,"id=?",new String[]{""+id});payload(id);}
    synchronized boolean add(Location f){long id=active();if(id==0)return false;SQLiteDatabase d=getWritableDatabase();try(Cursor r=d.rawQuery("SELECT started FROM routes WHERE id=?",new String[]{""+id})){if(!r.moveToFirst()||f.getTime()<r.getLong(0))return false;}
        try(Cursor c=d.rawQuery("SELECT hacc FROM points WHERE t=?",new String[]{""+f.getTime()})){if(c.moveToFirst()&&c.getDouble(0)<=f.getAccuracy())return false;}
        ContentValues v=new ContentValues();v.put("t",f.getTime());v.put("lat",f.getLatitude());v.put("lon",f.getLongitude());v.put("hacc",f.getAccuracy());v.put("route",id);v.put("provider",f.getProvider()==null?"unknown":f.getProvider());
        if(Build.VERSION.SDK_INT>=34&&f.hasMslAltitude()&&Double.isFinite(f.getMslAltitudeMeters()))v.put("alt",f.getMslAltitudeMeters());if(f.hasSpeed())v.put("speed",f.getSpeed());if(f.hasBearing())v.put("bearing",f.getBearing());d.insertWithOnConflict("points",null,v,SQLiteDatabase.CONFLICT_REPLACE);return true;
    }
    synchronized long count(){try(Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*) FROM points WHERE route=?",new String[]{""+active()})){c.moveToFirst();return c.getLong(0);}}
    synchronized long lastTime(){try(Cursor c=getReadableDatabase().rawQuery("SELECT COALESCE(MAX(t),0) FROM points WHERE route=?",new String[]{""+active()})){c.moveToFirst();return c.getLong(0);}}
    synchronized JSONArray list() throws Exception {JSONArray a=new JSONArray();try(Cursor c=getReadableDatabase().rawQuery("SELECT r.id,r.started,r.ended,r.state,COUNT(p.t),r.kind FROM routes r LEFT JOIN points p ON p.route=r.id GROUP BY r.id ORDER BY r.id DESC",null)){while(c.moveToNext())a.put(new JSONObject().put("id",c.getLong(0)).put("started",c.getLong(1)).put("ended",c.isNull(2)?JSONObject.NULL:c.getLong(2)).put("state",c.getString(3)).put("count",c.getLong(4)).put("mode",c.getString(5)));}return a;}
    synchronized void delete(long id){SQLiteDatabase d=getWritableDatabase();d.beginTransaction();try{try(Cursor c=d.rawQuery("SELECT state FROM routes WHERE id=?",new String[]{""+id})){if(c.moveToFirst()&&"recording".equals(c.getString(0)))throw new IllegalStateException("请先停止记录");}d.delete("points","route=?",new String[]{""+id});d.delete("routes","id=?",new String[]{""+id});d.setTransactionSuccessful();}finally{d.endTransaction();}}
    synchronized JSONObject payload(long id) throws Exception {
        String state,kind;try(Cursor c=getReadableDatabase().rawQuery("SELECT state,payload,kind FROM routes WHERE id=?",new String[]{""+id})){if(!c.moveToFirst())throw new IllegalStateException("路径不存在");state=c.getString(0);kind=c.getString(2);if(!c.isNull(1)){JSONObject cached=new JSONObject(c.getString(1));if(cached.has("points"))return cached;}}
        JSONArray raw=new JSONArray();String[] keys={"t","lat","lon","alt","hacc","speed","bearing","provider"};try(Cursor c=getReadableDatabase().rawQuery("SELECT t,lat,lon,alt,hacc,speed,bearing,provider FROM points WHERE route=? ORDER BY t",new String[]{""+id})){while(c.moveToNext()){JSONObject p=new JSONObject();for(int k=0;k<8;k++)p.put(keys[k],c.isNull(k)?JSONObject.NULL:k==0?c.getLong(k):k==7?c.getString(k):c.getDouble(k));raw.put(p);}}
        double[][] input=new double[raw.length()][6];for(int i=0;i<raw.length();i++){JSONObject p=raw.getJSONObject(i);input[i]=new double[]{p.getLong("t")/1000.0,p.getDouble("lat"),p.getDouble("lon"),p.optDouble("hacc",50),p.optDouble("speed",-1),"gps".equals(p.optString("provider"))?1:0};}
        boolean saved=!state.equals("recording");double[][] fit=saved?TrackSmoother.smooth(input):new double[0][];JSONArray points=new JSONArray();for(int i=0;i<raw.length();i++){JSONObject p=new JSONObject(raw.getJSONObject(i).toString());if(saved){double dy=(fit[i][0]-input[i][1])*111195.08,dx=(fit[i][1]-input[i][2])*111195.08*Math.cos(input[i][1]*Math.PI/180);p.put("lat",fit[i][0]).put("lon",fit[i][1]).put("correctionMeters",Math.hypot(dx,dy));}points.put(p);}
        JSONObject result=new JSONObject().put("schema","nef-gps-track/1").put("createdUtcMs",System.currentTimeMillis()).put("smoothing",saved?TrackSmoother.VERSION:"pending").put("points",points).put("rawPoints",raw).put("mode",kind);
        if(saved){ContentValues v=new ContentValues();v.put("payload",result.toString());getWritableDatabase().update("routes",v,"id=?",new String[]{""+id});}return result;
    }

}
