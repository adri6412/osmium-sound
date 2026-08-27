package com.osmium.sound.companion.service.localplayer;

import android.content.Context;
import android.provider.Settings;

import com.osmium.sound.companion.Preferences;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Locale;
import java.util.UUID;

/**
 * The identity this phone presents to Lyrion: a MAC-shaped player id and a uuid.
 *
 * <p>The id is derived from {@code ANDROID_ID} rather than drawn at random, so
 * that reinstalling the app produces the same player instead of leaving a dead
 * one behind in the server's player list. Only a truncated hash of it ever
 * leaves the device. The first byte is forced to the locally administered,
 * unicast pattern, which is the same convention squeezelite uses.
 *
 * <p>The string form is lower case, matching the {@code playerid} Lyrion
 * reports. Comparisons still go through {@link #matches(String)}: the app's own
 * {@code Util.formatMac} produces upper case, and a case-sensitive comparison
 * against it is the quietest way to break every check in this feature.
 */
public final class LocalPlayerIdentity {

    private static final String MAC_SALT = "|osmium-localplayer";

    private final byte[] mac;
    private final byte[] uuid;
    private final String macString;

    private LocalPlayerIdentity(byte[] mac, byte[] uuid) {
        this.mac = mac;
        this.uuid = uuid;
        this.macString = format(mac);
    }

    /** Loads the stored identity, generating and persisting one on first run. */
    public static LocalPlayerIdentity load(Context context, Preferences preferences) {
        byte[] mac = parseMac(preferences.getLocalPlayerMac());
        if (mac == null) {
            mac = deriveMac(context);
            preferences.setLocalPlayerMac(format(mac));
        }

        byte[] uuid = parseUuid(preferences.getLocalPlayerUuid());
        if (uuid == null) {
            uuid = randomUuid();
            preferences.setLocalPlayerUuid(toHex(uuid));
        }

        return new LocalPlayerIdentity(mac, uuid);
    }

    public byte[] mac() {
        return mac.clone();
    }

    public byte[] uuid() {
        return uuid.clone();
    }

    /** Player id as Lyrion spells it: lower case, colon separated. */
    public String macString() {
        return macString;
    }

    /** True when the given Lyrion player id is this phone, whatever its case. */
    public boolean matches(String playerId) {
        return playerId != null && playerId.equalsIgnoreCase(macString);
    }

    private static byte[] deriveMac(Context context) {
        byte[] seed;
        String androidId = null;
        try {
            androidId = Settings.Secure.getString(context.getContentResolver(),
                    Settings.Secure.ANDROID_ID);
        } catch (RuntimeException ignored) {
            // Some hardened ROMs refuse; a random id is still usable, it just
            // does not survive a reinstall.
        }
        if (androidId == null || androidId.isEmpty()) {
            seed = new byte[6];
            new SecureRandom().nextBytes(seed);
        } else {
            try {
                seed = MessageDigest.getInstance("SHA-256")
                        .digest((androidId + MAC_SALT).getBytes(StandardCharsets.UTF_8));
            } catch (NoSuchAlgorithmException e) {
                seed = new byte[6];
                new SecureRandom().nextBytes(seed);
            }
        }

        byte[] mac = new byte[6];
        System.arraycopy(seed, 0, mac, 0, 6);
        mac[0] = (byte) ((mac[0] & 0xFC) | 0x02); // locally administered, unicast
        return mac;
    }

    private static byte[] randomUuid() {
        UUID random = UUID.randomUUID();
        byte[] bytes = new byte[16];
        long most = random.getMostSignificantBits();
        long least = random.getLeastSignificantBits();
        for (int i = 0; i < 8; i++) {
            bytes[i] = (byte) (most >>> (56 - 8 * i));
            bytes[8 + i] = (byte) (least >>> (56 - 8 * i));
        }
        return bytes;
    }

    static String format(byte[] mac) {
        StringBuilder text = new StringBuilder(17);
        for (int i = 0; i < mac.length; i++) {
            if (i > 0) text.append(':');
            text.append(String.format(Locale.US, "%02x", mac[i] & 0xff));
        }
        return text.toString();
    }

    static byte[] parseMac(String text) {
        if (text == null) return null;
        String[] parts = text.split(":");
        if (parts.length != 6) return null;
        byte[] mac = new byte[6];
        try {
            for (int i = 0; i < 6; i++) {
                mac[i] = (byte) Integer.parseInt(parts[i], 16);
            }
        } catch (NumberFormatException e) {
            return null;
        }
        return mac;
    }

    static byte[] parseUuid(String hex) {
        if (hex == null || hex.length() != 32) return null;
        byte[] uuid = new byte[16];
        try {
            for (int i = 0; i < 16; i++) {
                uuid[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
            }
        } catch (NumberFormatException e) {
            return null;
        }
        return uuid;
    }

    static String toHex(byte[] bytes) {
        StringBuilder hex = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            hex.append(String.format(Locale.US, "%02x", b & 0xff));
        }
        return hex.toString();
    }
}
