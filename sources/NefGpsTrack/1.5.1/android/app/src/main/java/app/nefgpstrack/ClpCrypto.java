package app.nefgpstrack;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** CLP1 wire format. No Android dependency so the KDF can be cross checked on a PC. */
public final class ClpCrypto {
    public static final String FIXED_KEY = configuredPassword();
    private static String configuredPassword() {
        String value = System.getProperty("nefgpstrack.clp.password");
        if (value == null || value.isEmpty()) value = System.getenv("NEFGPSTRACK_CLP_PASSWORD");
        if (value == null || value.isEmpty()) {
            // Reflection keeps the standalone protocol test independent of Android/BuildConfig.
            try {
                value = (String) Class.forName("app.nefgpstrack.BuildConfig")
                        .getField("CLP_PASSWORD").get(null);
            } catch (ReflectiveOperationException ignored) { }
        }
        return value == null ? "" : value;
    }
    public static final int ITERATIONS = 310000;
    public static final int HEADER_LENGTH = 36;

    private ClpCrypto() {}

    public static byte[] header(byte[] salt, byte[] nonce) {
        if (salt.length != 16 || nonce.length != 12) throw new IllegalArgumentException("salt/nonce length");
        return ByteBuffer.allocate(HEADER_LENGTH).order(ByteOrder.BIG_ENDIAN)
                .put(new byte[]{'C','L','P','1'}).putInt(ITERATIONS).put(salt).put(nonce).array();
    }

    public static byte[] newSalt() {
        byte[] value = new byte[16];
        new SecureRandom().nextBytes(value);
        return value;
    }

    public static byte[] newNonce() {
        byte[] value = new byte[12];
        new SecureRandom().nextBytes(value);
        return value;
    }

    /** PBKDF2 takes UTF-8 bytes explicitly, including for non-ASCII passwords. */
    public static byte[] deriveKey(String password, byte[] salt) throws GeneralSecurityException {
        byte[] secret = password.getBytes(StandardCharsets.UTF_8);
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            byte[] block = ByteBuffer.allocate(salt.length + 4).order(ByteOrder.BIG_ENDIAN)
                    .put(salt).putInt(1).array();
            byte[] u = mac.doFinal(block);
            byte[] result = u.clone();
            for (int n = 1; n < ITERATIONS; n++) {
                u = mac.doFinal(u);
                for (int i = 0; i < result.length; i++) result[i] ^= u[i];
            }
            Arrays.fill(u, (byte) 0);
            return result;
        } finally {
            Arrays.fill(secret, (byte) 0);
        }
    }

    public static Cipher encryptor(String password, byte[] salt, byte[] nonce, byte[] header)
            throws GeneralSecurityException {
        byte[] key = deriveKey(password, salt);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(header);
            return cipher;
        } finally {
            Arrays.fill(key, (byte) 0);
        }
    }
}
