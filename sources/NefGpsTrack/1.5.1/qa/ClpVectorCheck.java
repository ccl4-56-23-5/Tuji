package app.nefgpstrack;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
import javax.crypto.Cipher;

/** Run with ClpCrypto.java to cross-check the published CLP1 UTF-8 vector. */
public final class ClpVectorCheck {
    public static void main(String[] args) throws Exception {
        HexFormat hex = HexFormat.of();
        byte[] salt = hex.parseHex("000102030405060708090a0b0c0d0e0f");
        byte[] nonce = hex.parseHex("101112131415161718191a1b");
        String password = "CLP1-测试密码-2026";
        String expectedKey = "6dc8d69107e0503d1cd70452acd73a7721e7b2f83c9a02fe2c4ee182fa0f6f6f";
        String actualKey = hex.formatHex(ClpCrypto.deriveKey(password, salt));
        if (!actualKey.equals(expectedKey)) throw new AssertionError("PBKDF2 mismatch: " + actualKey);
        byte[] header = ClpCrypto.header(salt, nonce);
        if (!hex.formatHex(header).equals(
                "434c50310004baf0000102030405060708090a0b0c0d0e0f101112131415161718191a1b")) {
            throw new AssertionError("header mismatch");
        }
        byte[] plain = Files.readAllBytes(Path.of(args[0]));
        Cipher cipher = ClpCrypto.encryptor(password, salt, nonce, header);
        String actual = hex.formatHex(cipher.doFinal(plain));
        String expected = Files.readString(Path.of(args[1]), StandardCharsets.US_ASCII).trim();
        if (!actual.equals(expected)) throw new AssertionError("AES-GCM mismatch");
        System.out.println("CLP1 Java UTF-8/PBKDF2/AES-GCM vector PASS");
    }
}
