package app.nefgpstrack;
import android.content.Context;
import android.net.Uri;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
final class TrackExport {
    static long export(Context c,Uri uri,long id)throws Exception{
        JSONObject payload;try(TrackDb db=new TrackDb(c)){if(db.active()==id)throw new IllegalStateException("请先结束当前路径");payload=db.payload(id);}
        byte[] salt=ClpCrypto.newSalt(),nonce=ClpCrypto.newNonce(),header=ClpCrypto.header(salt,nonce);
        byte[] ciphertext=ClpCrypto.encryptor(ClpCrypto.FIXED_KEY,salt,nonce,header).doFinal(payload.toString().getBytes(StandardCharsets.UTF_8));
        try(OutputStream out=c.getContentResolver().openOutputStream(uri,"wt")){if(out==null)throw new IllegalStateException("无法打开文件");out.write(header);out.write(ciphertext);}return payload.getJSONArray("points").length();
    }
}
