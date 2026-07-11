package com.osmium.sound.companion.appliance;

import android.content.ContentResolver;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.Preferences;

/**
 * Talks to the appliance's plain HTTP REST API (sources_server.py, port 8080) —
 * DSP status/control, room-correction FIR filter management, and backup/restore.
 * This is separate from the CometD/LMS protocol used everywhere else in the app
 * (see service/CometClient.java).
 * <p>
 * The base host:port and pairing token come from scanning the appliance's
 * "Phone control" QR code (see dialog/ServerAddressView.java), stored in
 * {@link Preferences#getApplianceApiAddress()} / {@link Preferences#getAppliancePairToken()}.
 * Before pairing, falls back to the LMS server's host on the default port 8080
 * (sources_server.py's fixed bind address) with no token — this matches what
 * the appliance accepts from the LAN for the FIR/backup/restore endpoints,
 * which don't require a token; the DSP status/set endpoints do, and will
 * fail with a 401 until the user has scanned the pairing QR.
 */
public final class ApplianceHttpClient {
    private static final String TAG = "ApplianceHttpClient";
    private static final int DEFAULT_API_PORT = 8080;
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

    private static final OkHttpClient client = new OkHttpClient.Builder().build();
    private static final Handler mainHandler = new Handler(Looper.getMainLooper());

    public interface JsonCallback {
        void onSuccess(JSONObject body);
        void onFailure(String message);
    }

    public interface StreamCallback {
        void onSuccess(InputStream body);
        void onFailure(String message);
    }

    private ApplianceHttpClient() {}

    private static String baseUrl() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        String apiAddress = preferences.getApplianceApiAddress();
        if (apiAddress == null || apiAddress.isEmpty()) {
            String lmsHost = preferences.getServerAddress().host();
            apiAddress = lmsHost + ":" + DEFAULT_API_PORT;
        }
        return "http://" + apiAddress;
    }

    private static Request.Builder authedRequest(String path) {
        Request.Builder builder = new Request.Builder().url(baseUrl() + path);
        String token = HiFiMediaPlayer.getPreferences().getAppliancePairToken();
        if (token != null && !token.isEmpty()) {
            builder.addHeader("Authorization", "Bearer " + token);
        }
        return builder;
    }

    private static void postMain(Runnable r) {
        mainHandler.post(r);
    }

    private static void enqueueJson(Request request, JsonCallback callback) {
        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                Log.w(TAG, "Request failed: " + request.url(), e);
                postMain(() -> callback.onFailure(e.getMessage()));
            }

            @Override
            public void onResponse(Call call, Response response) {
                try (ResponseBody body = response.body()) {
                    String text = body != null ? body.string() : "{}";
                    JSONObject json = new JSONObject(text);
                    postMain(() -> callback.onSuccess(json));
                } catch (IOException | JSONException e) {
                    postMain(() -> callback.onFailure(e.getMessage()));
                }
            }
        });
    }

    public static void dspStatus(JsonCallback callback) {
        enqueueJson(authedRequest("/api/dsp/status").get().build(), callback);
    }

    public static void dspSet(JSONObject dspConfig, JsonCallback callback) {
        RequestBody body = RequestBody.create(dspConfig.toString(), JSON);
        enqueueJson(authedRequest("/api/dsp/set").post(body).build(), callback);
    }

    public static void firStatus(JsonCallback callback) {
        enqueueJson(authedRequest("/api/dsp/fir").get().build(), callback);
    }

    public static void firDelete(JsonCallback callback) {
        enqueueJson(authedRequest("/api/dsp/fir").delete().build(), callback);
    }

    /** Uploads a filter file (.wav or .txt) picked via ActivityResultContracts.OpenDocument(). */
    public static void firUpload(Uri fileUri, ContentResolver resolver, String filename, JsonCallback callback) {
        try {
            InputStream in = resolver.openInputStream(fileUri);
            if (in == null) {
                callback.onFailure("Impossibile leggere il file selezionato");
                return;
            }
            byte[] data = readAll(in);
            String mime = filename.toLowerCase().endsWith(".txt") ? "text/plain" : "audio/x-wav";
            RequestBody fileBody = RequestBody.create(data, MediaType.get(mime));
            RequestBody multipart = new MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("file", filename, fileBody)
                    .build();
            enqueueJson(authedRequest("/api/dsp/fir").post(multipart).build(), callback);
        } catch (IOException e) {
            callback.onFailure(e.getMessage());
        }
    }

    /** Streams the backup tarball to the caller-supplied OutputStream (e.g. from CreateDocument). */
    public static void backupDownload(OutputStream destination, JsonCallback callback) {
        Request request = authedRequest("/api/backup").get().build();
        client.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                postMain(() -> callback.onFailure(e.getMessage()));
            }

            @Override
            public void onResponse(Call call, Response response) {
                try (ResponseBody body = response.body()) {
                    if (!response.isSuccessful() || body == null) {
                        postMain(() -> callback.onFailure("Backup non disponibile (" + response.code() + ")"));
                        return;
                    }
                    byte[] buffer = new byte[8192];
                    int n;
                    try (InputStream in = body.byteStream()) {
                        while ((n = in.read(buffer)) != -1) {
                            destination.write(buffer, 0, n);
                        }
                    }
                    postMain(() -> callback.onSuccess(new JSONObject()));
                } catch (IOException e) {
                    postMain(() -> callback.onFailure(e.getMessage()));
                }
            }
        });
    }

    /** Uploads a backup tarball picked via ActivityResultContracts.OpenDocument() to restore it. */
    public static void restoreUpload(Uri fileUri, ContentResolver resolver, JsonCallback callback) {
        try {
            InputStream in = resolver.openInputStream(fileUri);
            if (in == null) {
                callback.onFailure("Impossibile leggere il file selezionato");
                return;
            }
            byte[] data = readAll(in);
            RequestBody fileBody = RequestBody.create(data, MediaType.get("application/gzip"));
            RequestBody multipart = new MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("file", "restore.tar.gz", fileBody)
                    .build();
            enqueueJson(authedRequest("/api/restore").post(multipart).build(), callback);
        } catch (IOException e) {
            callback.onFailure(e.getMessage());
        }
    }

    private static byte[] readAll(InputStream in) throws IOException {
        try (InputStream stream = in) {
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int n;
            while ((n = stream.read(buffer)) != -1) {
                out.write(buffer, 0, n);
            }
            return out.toByteArray();
        }
    }
}
