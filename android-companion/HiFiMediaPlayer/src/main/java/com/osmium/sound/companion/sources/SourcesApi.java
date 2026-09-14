package com.osmium.sound.companion.sources;

import android.content.Context;
import android.net.Uri;

import androidx.annotation.Nullable;

import org.json.JSONException;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.appliance.ApplianceHttpClient.JsonCallback;

/**
 * The music-sources endpoints of sources_server.py, called directly at
 * /api/&lt;x&gt; (the web admin reaches the same routes through webui_server's
 * session-gated /api/system/&lt;x&gt; forwarders — see admin-webui/src/api.js).
 * Every one of them requires the pairing token, which ApplianceHttpClient sends.
 * <p>
 * Each call carries {@code ?lang=} so the translated {@code message} fields come
 * back in the language the app is shown in: sources_server.py's _req_lang()
 * reads it before anything else, and ApplianceHttpClient sends no X-UI-Lang.
 * <p>
 * Like the rest of ApplianceHttpClient, onSuccess fires for any JSON body,
 * error bodies included: check {@link #failed(JSONObject)}.
 */
public final class SourcesApi {
    private final String lang;

    public SourcesApi(Context context) {
        String language = context.getResources().getConfiguration().getLocales().get(0).getLanguage();
        lang = "it".equals(language) ? "it" : "en";
    }

    /** An error body from sources_server.py: {@code { success: false, code, message[, detail] }}. */
    public static boolean failed(JSONObject body) {
        return body == null || !body.optBoolean("success", true);
    }

    /** The server's own (already translated) message, or {@code fallback}. */
    public static String message(@Nullable JSONObject body, String fallback) {
        String m = str(body, "message");
        return m.isEmpty() ? fallback : m;
    }

    /** A string field, "" when absent or JSON null (optString would give "null"). */
    public static String str(@Nullable JSONObject o, String key) {
        return o == null || o.isNull(key) ? "" : o.optString(key, "");
    }

    private String path(String path) {
        return path + (path.contains("?") ? "&" : "?") + "lang=" + lang;
    }

    private String withQuery(String path, String name, String value) {
        return path(path + "?" + name + "=" + Uri.encode(value != null ? value : ""));
    }

    private static JSONObject json(Object... pairs) {
        JSONObject o = new JSONObject();
        try {
            for (int i = 0; i + 1 < pairs.length; i += 2) {
                o.put((String) pairs[i], pairs[i + 1]);
            }
        } catch (JSONException ignored) {
            // keys are our own constants
        }
        return o;
    }

    // ── Active sources ────────────────────────────────────────────────
    public void list(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/sources"), cb);
    }

    public void remove(String id, JsonCallback cb) {
        ApplianceHttpClient.deleteJson(path("/api/sources/" + Uri.encode(id)), cb);
    }

    public void setRw(String id, boolean rw, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/" + Uri.encode(id) + "/rw"), json("rw", rw), cb);
    }

    public void setSubpath(String id, String subpath, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/" + Uri.encode(id) + "/subpath"), json("subpath", subpath), cb);
    }

    public void browse(String id, String relPath, JsonCallback cb) {
        ApplianceHttpClient.getJson(withQuery("/api/sources/" + Uri.encode(id) + "/browse", "path", relPath), cb);
    }

    // ── Local folders ─────────────────────────────────────────────────
    public void addLocal(String folder, boolean samba, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/local"), json("path", folder, "samba", samba), cb);
    }

    public void localBrowse(String folder, JsonCallback cb) {
        ApplianceHttpClient.getJson(withQuery("/api/local/browse", "path", folder), cb);
    }

    public void localMkdir(String parent, String name, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/local/mkdir"), json("path", parent, "name", name), cb);
    }

    // ── Network folders (SMB) ─────────────────────────────────────────
    public void addSmb(String server, String share, String username, String password, boolean rw,
                       JsonCallback cb) {
        // defer_activation: mount only; the source reaches Lyrion once the
        // owner picks the whole share or a subfolder (setSubpath).
        ApplianceHttpClient.postJson(path("/api/sources/smb"), json("server", server, "share", share,
                "username", username, "password", password, "rw", rw, "defer_activation", true), cb);
    }

    public void smbDiscoverStart(JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/smb/discover"), null, cb);
    }

    public void smbDiscoverStatus(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/sources/smb/discover"), cb);
    }

    public void smbShares(String server, String username, String password, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/smb/shares"),
                json("server", server, "username", username, "password", password), cb);
    }

    public void smbTest(String server, String share, String username, String password, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/sources/smb/test"),
                json("server", server, "share", share, "username", username, "password", password), cb);
    }

    // ── USB and internal disks ────────────────────────────────────────
    public void usbList(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/usb"), cb);
    }

    public void usbAdopt(String device, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/usb/adopt"), json("device", device), cb);
    }

    public void internalDisks(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/internal/disks"), cb);
    }

    public void internalAdopt(String device, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/internal/adopt"), json("device", device), cb);
    }

    public void internalFormat(String device, String fs, String label, String confirm, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/internal/format"),
                json("device", device, "fs", fs, "label", label, "confirm", confirm), cb);
    }

    public void internalFormatStatus(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/internal/format/status"), cb);
    }

    // ── Shared folders (Samba) ────────────────────────────────────────
    public void internalSmb(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/internal/smb"), cb);
    }

    public void internalSmbRegenerate(JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/internal/smb/regenerate"), null, cb);
    }

    // ── Playlist folder ───────────────────────────────────────────────
    public void playlistdirGet(JsonCallback cb) {
        ApplianceHttpClient.getJson(path("/api/playlistdir"), cb);
    }

    public void playlistdirSet(String folder, JsonCallback cb) {
        ApplianceHttpClient.postJson(path("/api/playlistdir"), json("path", folder), cb);
    }
}
