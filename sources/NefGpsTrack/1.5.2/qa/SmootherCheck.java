import app.nefgpstrack.*;
import java.nio.file.*;
import java.util.*;
public class SmootherCheck {
    public static void main(String[] args)throws Exception{
        List<String> lines=Files.readAllLines(Path.of(args[0]));double[][] p=new double[lines.size()][6];
        for(int i=0;i<p.length;i++){String[] v=lines.get(i).split(",");for(int j=0;j<6;j++)p[i][j]=Double.parseDouble(v[j]);}
        double[][] fit=TrackSmoother.smooth(p);StringBuilder csv=new StringBuilder();for(double[] r:fit)csv.append(r[0]).append(",").append(r[1]).append("\n");Files.writeString(Path.of(args[1]),csv);
        byte[] salt=ClpCrypto.newSalt(),nonce=ClpCrypto.newNonce(),header=ClpCrypto.header(salt,nonce),plain=Files.readAllBytes(Path.of(args[2]));
        byte[] encrypted=ClpCrypto.encryptor(ClpCrypto.FIXED_KEY,salt,nonce,header).doFinal(plain);byte[] out=Arrays.copyOf(header,header.length+encrypted.length);System.arraycopy(encrypted,0,out,header.length,encrypted.length);Files.write(Path.of(args[3]),out);
    }
}
