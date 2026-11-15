package app.nefgpstrack;
import android.content.*;
import android.database.*;
import android.database.sqlite.*;
import android.location.Location;
import org.json.*;

final class TrackDb extends SQLiteOpenHelper {
    private static final String[] ALTITUDE_COLUMNS = {"alt", "ellipsoidAlt", "verticalAccuracy",
            "altAccuracy", "altSource", "altProvider", "altHacc", "altLat", "altLon"};
    TrackDb(Context c){super(c,"track.db",null,4);setWriteAheadLoggingEnabled(true);}
    public void onCreate(SQLiteDatabase d){d.execSQL("CREATE TABLE points(t INTEGER PRIMARY KEY,lat REAL NOT NULL,lon REAL NOT NULL,alt REAL,hacc REAL NOT NULL,speed REAL,bearing REAL,provider TEXT NOT NULL,route INTEGER NOT NULL DEFAULT 0,ellipsoidAlt REAL,verticalAccuracy REAL,altAccuracy REAL,altSource TEXT,altProvider TEXT,altHacc REAL,altLat REAL,altLon REAL)");routes(d);}
    private void routes(SQLiteDatabase d){d.execSQL("CREATE TABLE routes(id INTEGER PRIMARY KEY AUTOINCREMENT,started INTEGER NOT NULL,ended INTEGER,state TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'track',payload TEXT)");d.execSQL("CREATE INDEX points_route ON points(route,t)");}
    public void onUpgrade(SQLiteDatabase d,int old,int next){if(old==1){d.execSQL("ALTER TABLE points ADD COLUMN route INTEGER NOT NULL DEFAULT 0");routes(d);d.execSQL("INSERT INTO routes(started,ended,state) SELECT MIN(t),MAX(t),'saved' FROM points HAVING COUNT(*)>0");d.execSQL("UPDATE points SET route=(SELECT MAX(id) FROM routes)");}if(old==2)d.execSQL("ALTER TABLE routes ADD COLUMN kind TEXT NOT NULL DEFAULT 'track'");
        if(old<4){for(String column:ALTITUDE_COLUMNS){if(!column.equals("alt"))d.execSQL("ALTER TABLE points ADD COLUMN "+column+(column.equals("altSource")||column.equals("altProvider")?" TEXT":" REAL"));}
            d.execSQL("UPDATE points SET altSource=CASE WHEN alt IS NULL THEN 'unknown' ELSE 'legacy-msl' END,altProvider=provider,altHacc=hacc,altLat=lat,altLon=lon");}
    }
    synchronized long active(){try(Cursor c=getReadableDatabase().rawQuery("SELECT id FROM routes WHERE state='recording' ORDER BY id DESC LIMIT 1",null)){return c.moveToFirst()?c.getLong(0):0;}}
    synchronized long activeStarted(){try(Cursor c=getReadableDatabase().rawQuery("SELECT started FROM routes WHERE state='recording' ORDER BY id DESC LIMIT 1",null)){return c.moveToFirst()?c.getLong(0):Long.MAX_VALUE;}}
    synchronized long begin(){return begin(false);}
    synchronized long begin(boolean single){long id=active();if(id!=0)return id;ContentValues v=new ContentValues();v.put("started",System.currentTimeMillis());v.put("state","recording");v.put("kind",single?"single":"track");return getWritableDatabase().insertOrThrow("routes",null,v);}
    synchronized void finish() throws Exception {long id=active();if(id==0)return;ContentValues v=new ContentValues();v.put("ended",System.currentTimeMillis());v.put("state","saved");getWritableDatabase().update("routes",v,"id=?",new String[]{""+id});payload(id);}
    synchronized boolean add(Location f, AltitudeResolver.Reading altitude){
        long id=active();if(id==0)return false;
        SQLiteDatabase d=getWritableDatabase();
        try(Cursor r=d.rawQuery("SELECT started FROM routes WHERE id=?",new String[]{""+id})){
            if(!r.moveToFirst()||f.getTime()<r.getLong(0))return false;
        }
        ContentValues incoming=new ContentValues();
        incoming.put("t",f.getTime());incoming.put("lat",f.getLatitude());incoming.put("lon",f.getLongitude());
        incoming.put("hacc",f.getAccuracy());incoming.put("route",id);
        incoming.put("provider",f.getProvider()==null?"unknown":f.getProvider());
        putFinite(incoming,"speed",f.hasSpeed()?f.getSpeed():Double.NaN);
        putFinite(incoming,"bearing",f.hasBearing()?f.getBearing():Double.NaN);
        putFinite(incoming,"alt",altitude.msl);putFinite(incoming,"ellipsoidAlt",altitude.ellipsoid);
        putFinite(incoming,"verticalAccuracy",altitude.verticalAccuracy);putFinite(incoming,"altAccuracy",altitude.accuracy);
        incoming.put("altSource",altitude.source);incoming.put("altProvider",altitude.provider);
        putFinite(incoming,"altHacc",altitude.horizontalAccuracy);
        putFinite(incoming,"altLat",altitude.latitude);putFinite(incoming,"altLon",altitude.longitude);
        d.beginTransaction();
        try{
            ContentValues previous=null;
            try(Cursor c=d.rawQuery("SELECT * FROM points WHERE t=?",new String[]{""+f.getTime()})){
                if(c.moveToFirst()){previous=new ContentValues();DatabaseUtils.cursorRowToContentValues(c,previous);}
            }
            if(previous!=null){
                // A repeated timestamp must never move a point out of an older route.
                if(previous.getAsLong("route")!=id)return false;
                boolean replaceHorizontal=f.getAccuracy()<number(previous,"hacc");
                boolean compatible=compatible(previous,incoming);
                ContentValues horizontal=replaceHorizontal?incoming:previous;
                ContentValues vertical=horizontal;
                if(compatible){
                    vertical=preferAltitude(incoming,previous)?incoming:previous;
                    // The altitude may already originate from a different provider. Check
                    // its original position, so repeated replacements cannot walk it away.
                    if(!compatibleAltitude(horizontal,vertical))vertical=horizontal;
                }
                if(!replaceHorizontal&&vertical==previous)return false;
                ContentValues combined=new ContentValues(horizontal);
                for(String key:ALTITUDE_COLUMNS){
                    Object value=vertical.get(key);
                    if(value==null)combined.putNull(key);
                    else if(value instanceof String)combined.put(key,(String)value);
                    else combined.put(key,((Number)value).doubleValue());
                }
                incoming=combined;
            }
            if(previous==null)d.insertOrThrow("points",null,incoming);
            else d.update("points",incoming,"t=? AND route=?",new String[]{""+f.getTime(),""+id});
            d.setTransactionSuccessful();
            return true;
        }finally{d.endTransaction();}
    }

    private static void putFinite(ContentValues values,String key,double value){
        if(Double.isFinite(value))values.put(key,value);else values.putNull(key);
    }
    private static double number(ContentValues values,String key){
        Double value=values.getAsDouble(key);return value==null?Double.NaN:value;
    }
    private static boolean compatible(ContentValues a,ContentValues b){
        float[] distance=new float[1];
        Location.distanceBetween(number(a,"lat"),number(a,"lon"),number(b,"lat"),number(b,"lon"),distance);
        double limit=Math.max(10,Math.min(100,number(a,"hacc")+number(b,"hacc")));
        return distance[0]<=limit;
    }
    private static boolean compatibleAltitude(ContentValues horizontal,ContentValues vertical){
        if(!Double.isFinite(number(vertical,"alt"))&&!Double.isFinite(number(vertical,"ellipsoidAlt")))return true;
        float[] distance=new float[1];
        Location.distanceBetween(number(horizontal,"lat"),number(horizontal,"lon"),
                number(vertical,"altLat"),number(vertical,"altLon"),distance);
        double limit=Math.max(10,Math.min(100,number(horizontal,"hacc")+number(vertical,"altHacc")));
        return distance[0]<=limit;
    }
    private static boolean preferAltitude(ContentValues newer,ContentValues older){
        boolean newMsl=Double.isFinite(number(newer,"alt")),oldMsl=Double.isFinite(number(older,"alt"));
        if(newMsl!=oldMsl)return newMsl;
        boolean newHeight=newMsl||Double.isFinite(number(newer,"ellipsoidAlt"));
        boolean oldHeight=oldMsl||Double.isFinite(number(older,"ellipsoidAlt"));
        if(newHeight!=oldHeight)return newHeight;
        if(!newHeight)return false;
        String accuracyKey=newMsl?"altAccuracy":"verticalAccuracy";
        double newAccuracy=number(newer,accuracyKey),oldAccuracy=number(older,accuracyKey);
        if(Double.isFinite(newAccuracy)!=Double.isFinite(oldAccuracy))return Double.isFinite(newAccuracy);
        if(Double.isFinite(newAccuracy)&&newAccuracy!=oldAccuracy)return newAccuracy<oldAccuracy;
        return number(newer,"altHacc")<number(older,"altHacc");
    }
    synchronized long count(){try(Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*) FROM points WHERE route=?",new String[]{""+active()})){c.moveToFirst();return c.getLong(0);}}
    synchronized long lastTime(){try(Cursor c=getReadableDatabase().rawQuery("SELECT COALESCE(MAX(t),0) FROM points WHERE route=?",new String[]{""+active()})){c.moveToFirst();return c.getLong(0);}}
    synchronized JSONArray list() throws Exception {JSONArray a=new JSONArray();try(Cursor c=getReadableDatabase().rawQuery("SELECT r.id,r.started,r.ended,r.state,COUNT(p.t),r.kind FROM routes r LEFT JOIN points p ON p.route=r.id GROUP BY r.id ORDER BY r.id DESC",null)){while(c.moveToNext())a.put(new JSONObject().put("id",c.getLong(0)).put("started",c.getLong(1)).put("ended",c.isNull(2)?JSONObject.NULL:c.getLong(2)).put("state",c.getString(3)).put("count",c.getLong(4)).put("mode",c.getString(5)));}return a;}
    synchronized void delete(long id){SQLiteDatabase d=getWritableDatabase();d.beginTransaction();try{try(Cursor c=d.rawQuery("SELECT state FROM routes WHERE id=?",new String[]{""+id})){if(c.moveToFirst()&&"recording".equals(c.getString(0)))throw new IllegalStateException("请先停止记录");}d.delete("points","route=?",new String[]{""+id});d.delete("routes","id=?",new String[]{""+id});d.setTransactionSuccessful();}finally{d.endTransaction();}}
    synchronized JSONObject payload(long id) throws Exception {
        String state,kind;try(Cursor c=getReadableDatabase().rawQuery("SELECT state,payload,kind FROM routes WHERE id=?",new String[]{""+id})){if(!c.moveToFirst())throw new IllegalStateException("路径不存在");state=c.getString(0);kind=c.getString(2);if(!c.isNull(1)){JSONObject cached=new JSONObject(c.getString(1));if(cached.has("points"))return cached;}}
        JSONArray raw=new JSONArray();String[] keys={"t","lat","lon","alt","hacc","speed","bearing","provider","ellipsoidAlt","verticalAccuracy","altAccuracy","altSource","altProvider","altHacc","altLat","altLon"};try(Cursor c=getReadableDatabase().rawQuery("SELECT "+String.join(",",keys)+" FROM points WHERE route=? ORDER BY t",new String[]{""+id})){while(c.moveToNext()){JSONObject p=new JSONObject();for(int k=0;k<keys.length;k++)p.put(keys[k],c.isNull(k)?JSONObject.NULL:k==0?c.getLong(k):k==7||k==11||k==12?c.getString(k):c.getDouble(k));raw.put(p);}}
        double[][] input=new double[raw.length()][6];for(int i=0;i<raw.length();i++){JSONObject p=raw.getJSONObject(i);input[i]=new double[]{p.getLong("t")/1000.0,p.getDouble("lat"),p.getDouble("lon"),p.optDouble("hacc",50),p.optDouble("speed",-1),"gps".equals(p.optString("provider"))?1:0};}
        boolean saved=!state.equals("recording");double[][] fit=saved?TrackSmoother.smooth(input):new double[0][];JSONArray points=new JSONArray();for(int i=0;i<raw.length();i++){JSONObject p=new JSONObject(raw.getJSONObject(i).toString());if(saved){double dy=(fit[i][0]-input[i][1])*111195.08,dx=(fit[i][1]-input[i][2])*111195.08*Math.cos(input[i][1]*Math.PI/180);p.put("lat",fit[i][0]).put("lon",fit[i][1]).put("correctionMeters",Math.hypot(dx,dy));}points.put(p);}
        JSONObject result=new JSONObject().put("schema","nef-gps-track/1").put("createdUtcMs",System.currentTimeMillis()).put("smoothing",saved?TrackSmoother.VERSION:"pending").put("altitudeAcquisition",AltitudeResolver.VERSION).put("points",points).put("rawPoints",raw).put("mode",kind);
        if(saved){ContentValues v=new ContentValues();v.put("payload",result.toString());getWritableDatabase().update("routes",v,"id=?",new String[]{""+id});}return result;
    }

}
