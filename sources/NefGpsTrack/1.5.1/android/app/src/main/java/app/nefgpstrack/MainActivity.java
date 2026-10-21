package app.nefgpstrack;
import android.Manifest;
import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.provider.Settings;
import android.webkit.*;
import org.json.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private boolean pendingSingle;
    private WebView web;private long exportId;private final ExecutorService worker=Executors.newSingleThreadExecutor();
    @Override public void onCreate(Bundle state){super.onCreate(state);if(state!=null)exportId=state.getLong("exportId");
        getWindow().setStatusBarColor(0xfff3f8ff);getWindow().setNavigationBarColor(0xfff3f8ff);getWindow().getDecorView().setSystemUiVisibility(android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        web=new WebView(this);web.setBackgroundColor(0xfff3f8ff);web.getSettings().setJavaScriptEnabled(true);web.getSettings().setDomStorageEnabled(true);web.getSettings().setAllowFileAccess(false);web.getSettings().setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient(){
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest req){Uri u=req.getUrl();if("app.nefgpstrack.local".equals(u.getHost())){String path=u.getPath();if(path==null||path.contains(".."))return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));try{String name=path.equals("/")?"index.html":path.substring(1);String mime=name.endsWith(".css")?"text/css":name.endsWith(".js")?"application/javascript":name.endsWith(".png")?"image/png":"text/html";return new WebResourceResponse(mime,"UTF-8",getAssets().open("ui/"+name));}catch(Exception e){return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));}}return super.shouldInterceptRequest(v,req);}
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest req){return true;}
        });web.addJavascriptInterface(new Bridge(),"Native");android.widget.FrameLayout frame=new android.widget.FrameLayout(this);frame.addView(web,new android.widget.FrameLayout.LayoutParams(-1,-1));frame.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});setContentView(frame);web.loadUrl("https://app.nefgpstrack.local/index.html");
    }
    @Override protected void onSaveInstanceState(Bundle b){b.putLong("exportId",exportId);super.onSaveInstanceState(b);}
    @Override protected void onDestroy(){web.removeJavascriptInterface("Native");web.destroy();worker.shutdown();super.onDestroy();}
    final class Bridge {
        @JavascriptInterface public void request(String token,String action,String input){worker.execute(()->{try{JSONObject args=new JSONObject(input),result=new JSONObject();switch(action){
            case "state":XiaomiIsland.probe(MainActivity.this,false);try(TrackDb db=new TrackDb(MainActivity.this)){SharedPreferences p=getSharedPreferences(TrackService.PREFS,MODE_PRIVATE);result.put("island",XiaomiIsland.status(MainActivity.this)).put("started",p.getLong("recordStarted",0L)).put("platform","android").put("single",p.getBoolean("single",false)).put("active",p.getBoolean(TrackService.KEY_ACTIVE,false)).put("finishing",TrackService.finishing).put("mode",p.getInt(TrackService.KEY_MODE,0)).put("error",p.getString(TrackService.KEY_ERROR,"")).put("count",db.count()).put("last",db.lastTime()).put("routes",db.list());}break;
            case "view":try(TrackDb db=new TrackDb(MainActivity.this)){result=db.payload(args.getLong("id"));}break;
            case "delete":try(TrackDb db=new TrackDb(MainActivity.this)){db.delete(args.getLong("id"));}break;
            case "start":finishInterruptedRoute();pendingSingle=false;runOnUiThread(()->requestStart());break;
            case "single":finishInterruptedRoute();pendingSingle=true;runOnUiThread(()->requestStart());break;
            case "stop":runOnUiThread(()->startService(new Intent(MainActivity.this,TrackService.class).setAction(TrackService.ACTION_STOP)));break;
            case "mode":int mode=args.getInt("value");getSharedPreferences(TrackService.PREFS,MODE_PRIVATE).edit().putInt(TrackService.KEY_MODE,mode==1?1:0).apply();if(getSharedPreferences(TrackService.PREFS,MODE_PRIVATE).getBoolean(TrackService.KEY_ACTIVE,false))runOnUiThread(()->startService(new Intent(MainActivity.this,TrackService.class).setAction(TrackService.ACTION_CONFIG)));break;
            case "export":long id=args.getLong("id");runOnUiThread(()->{exportId=id;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE,"NefGpsTrack-"+id+".clp");startActivityForResult(i,13);});break;
            case "island-check":XiaomiIsland.probe(MainActivity.this,true);result=XiaomiIsland.status(MainActivity.this);break;
            case "island-diagnose":XiaomiIsland.probe(MainActivity.this,true);result=XiaomiIsland.diagnose(MainActivity.this);break;
            case "island-test":String payload=XiaomiIsland.sendTest(MainActivity.this);result.put("payload",payload).put("status",XiaomiIsland.status(MainActivity.this).getString("status")).put("blockedBy",XiaomiIsland.blockedBy(MainActivity.this));break;
            case "island-business":XiaomiIsland.setBusiness(MainActivity.this,args.optString("value",""));result=XiaomiIsland.status(MainActivity.this);break;
            case "island-toggle":getSharedPreferences(TrackService.PREFS,MODE_PRIVATE).edit().putBoolean("islandEnabled",args.getBoolean("enabled")).apply();if(getSharedPreferences(TrackService.PREFS,MODE_PRIVATE).getBoolean(TrackService.KEY_ACTIVE,false))runOnUiThread(()->startService(new Intent(MainActivity.this,TrackService.class).setAction(TrackService.ACTION_CONFIG)));break;
            case "notification-settings":runOnUiThread(()->{try{startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,getPackageName()));}catch(Exception e){startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName())));}});break;
            case "settings":runOnUiThread(()->startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName()))));break;
            case "battery":runOnUiThread(()->{try{startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getPackageName())));}catch(Exception e){startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));}});break;
            default:throw new IllegalArgumentException("未知操作");
        }reply(token,result,null);}catch(Exception e){reply(token,null,e.getMessage());}});}
    }
    private void reply(String token,JSONObject data,String error){runOnUiThread(()->{if(isFinishing()||isDestroyed())return;web.evaluateJavascript("window.nativeReply("+JSONObject.quote(token)+","+(data==null?"null":data.toString())+","+(error==null?"null":JSONObject.quote(error))+")",null);});}
    private void finishInterruptedRoute()throws Exception{
        SharedPreferences p=getSharedPreferences(TrackService.PREFS,MODE_PRIVATE);
        if(TrackService.finishing||p.getBoolean(TrackService.KEY_ACTIVE,false))throw new IllegalStateException("请先结束当前记录");
        // A failed service can leave a recording row after its active flag clears.
        // Save it on the bridge worker before opening an independent new session.
        try(TrackDb db=new TrackDb(this)){long id=db.active();if(id!=0){db.finish();JSONObject old=db.payload(id);if("single".equals(old.optString("mode"))&&old.getJSONArray("points").length()==0)db.delete(id);}}
    }
    private void requestStart(){if(TrackService.finishing||getSharedPreferences(TrackService.PREFS,MODE_PRIVATE).getBoolean(TrackService.KEY_ACTIVE,false))return;if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},11);return;}try{startForegroundService(new Intent(this,TrackService.class).setAction(pendingSingle?TrackService.ACTION_SINGLE:TrackService.ACTION_START));if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},12);}catch(Exception e){notice("无法启动",e.getMessage());}}
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results){super.onRequestPermissionsResult(code,permissions,results);if(code==11){if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED)requestStart();else notice("需要精确定位","请允许精确定位后开始记录。");}}
    @Override protected void onActivityResult(int req,int result,Intent data){super.onActivityResult(req,result,data);if(req==13&&result==RESULT_OK&&data!=null&&data.getData()!=null){Uri uri=data.getData();long id=exportId;worker.execute(()->{try{long n=TrackExport.export(getApplicationContext(),uri,id);runOnUiThread(()->notice("已导出","已保存"+n+"个定位节点（已滤除定位漂移）与原始点；平滑曲线由电脑端生成。"));}catch(Exception e){try{getContentResolver().delete(uri,null,null);}catch(Exception ignored){}runOnUiThread(()->notice("导出失败",e.getMessage()));}});}}
    private void notice(String title,String text){if(!isFinishing()&&!isDestroyed())new AlertDialog.Builder(this).setTitle(title).setMessage(text).setPositiveButton("知道了",null).show();}
}
