package com.opencompanion.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * API Key 与配置的加密存储。
 *
 * 为什么不能直接存 SharedPreferences：那是明文 XML，adb backup / root /
 * 设备被物理接触时能被直接读出。API Key 一旦泄露，别人可以拿它刷你的额度。
 *
 * 方案：用 Android Keystore 生成一把**不可导出**的 AES-256 密钥
 * （密钥本身保存在 TEE/StrongBox 中，App 无法读出，只能请求它加解密），
 * 用它以 AES/GCM 加密后，再把密文写进 SharedPreferences。
 *
 * 局限要说清楚：这能防住"读取文件"，防不住"设备已被 root 且攻击者能
 * 在 App 进程内执行代码"。手机上不存在绝对安全，这是行业内的通用做法。
 */
public final class SecureStore {

    private static final String ANDROID_KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS = "opencompanion_master_key";
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int GCM_TAG_BITS = 128;
    private static final int IV_BYTES = 12;

    private SecureStore() { }

    /** 取（或首次创建）不可导出的主密钥。 */
    private static SecretKey masterKey() throws Exception {
        KeyStore ks = KeyStore.getInstance(ANDROID_KEYSTORE);
        ks.load(null);

        if (ks.containsAlias(KEY_ALIAS)) {
            return ((KeyStore.SecretKeyEntry) ks.getEntry(KEY_ALIAS, null)).getSecretKey();
        }

        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE);
        KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                // 不要求解锁设备才能用，否则侣问候等在锁屏时也会失效
                .setUserAuthenticationRequired(false)
                .build();
        kg.init(spec);
        return kg.generateKey();
    }

    /** 加密。返回 "base64(iv):base64(ciphertext)"，失败返回 null。 */
    public static String encrypt(String plain) {
        if (plain == null) return null;
        try {
            SecretKey key = masterKey();
            Cipher c = Cipher.getInstance(TRANSFORMATION);
            c.init(Cipher.ENCRYPT_MODE, key);
            byte[] iv = c.getIV();
            byte[] ct = c.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            return Base64.encodeToString(iv, Base64.NO_WRAP)
                    + ":" + Base64.encodeToString(ct, Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        }
    }

    /** 解密。失败（密钥被清除/数据损坏）返回 null。 */
    public static String decrypt(String stored) {
        if (stored == null || !stored.contains(":")) return null;
        try {
            String[] parts = stored.split(":", 2);
            byte[] iv = Base64.decode(parts[0], Base64.NO_WRAP);
            byte[] ct = Base64.decode(parts[1], Base64.NO_WRAP);

            Cipher c = Cipher.getInstance(TRANSFORMATION);
            c.init(Cipher.DECRYPT_MODE, masterKey(), new GCMParameterSpec(GCM_TAG_BITS, iv));
            byte[] pt = c.doFinal(ct);
            return new String(pt, StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    // ── 便捷读写 ────────────────────────────────────────────
    public static void put(Context ctx, String k, String v) {
        SharedPreferences sp = ctx.getSharedPreferences("opencompanion", Context.MODE_PRIVATE);
        if (v == null) {
            sp.edit().remove(k).apply();
        } else {
            String enc = encrypt(v);
            if (enc != null) sp.edit().putString(k, enc).apply();
        }
    }

    public static String get(Context ctx, String k, String def) {
        SharedPreferences sp = ctx.getSharedPreferences("opencompanion", Context.MODE_PRIVATE);
        String stored = sp.getString(k, null);
        if (stored == null) return def;
        String plain = decrypt(stored);
        return plain != null ? plain : def;
    }

    /** 把指定前缀下所有旧数据清掉（注销时用）。 */
    public static void clearAll(Context ctx) {
        SharedPreferences sp = ctx.getSharedPreferences("opencompanion", Context.MODE_PRIVATE);
        sp.edit().clear().apply();
    }
}
