package com.osmium.sound.companion;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Base64;
import android.view.View;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.RadioGroup;
import android.widget.TextView;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

import com.osmium.sound.companion.dialog.PlaybackPrefsDialog;
import com.osmium.sound.companion.service.ISqueezeService;
import com.osmium.sound.companion.service.SqueezeService;

/**
 * The web admin's Settings → Playback card (admin-webui Settings.vue): track
 * transitions / ReplayGain / fixed volume (the existing PlaybackPrefsDialog),
 * the animated VU meters, their style, the VU meter store, and how soon the
 * device's screen opens "now playing" on its own.
 */
public class AppliancePlaybackActivity extends ApplianceSettingsActivity {
    // Same cadence as the web admin while the device checks the list or installs.
    private static final long STORE_POLL_MS = 1500;
    private static final int[] AUTOEXPAND_CHOICES = {0, 3, 5, 10, 15};

    private View vuBlock;
    private RadioGroup vuGroup;
    private View styleBlock;
    private RadioGroup styleGroup;
    private View storeBlock;
    private TextView storeStatus;
    private LinearLayout storeList;
    private MaterialButton storeCheck;
    private View autoExpandBlock;
    private RadioGroup autoExpandGroup;

    private boolean vuEnabled = true;
    private String vuStyle = "classic";
    private int styleCount;
    private int autoExpand;
    private boolean storeBusy;
    private boolean storeSeenSent;
    private final Handler storePoll = new Handler(Looper.getMainLooper());
    private final Runnable storePollTask = () -> loadStore(false);

    private ISqueezeService service;
    private final ServiceConnection serviceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            service = (ISqueezeService) binder;
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            service = null;
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.appliance_section_playback, R.layout.appliance_playback);
        bindService(new Intent(this, SqueezeService.class), serviceConnection, Context.BIND_AUTO_CREATE);

        vuBlock = findViewById(R.id.playback_vu_block);
        vuGroup = findViewById(R.id.playback_vu_group);
        styleBlock = findViewById(R.id.playback_vu_style_block);
        styleGroup = findViewById(R.id.playback_vu_style_group);
        storeBlock = findViewById(R.id.playback_store_block);
        storeStatus = findViewById(R.id.playback_store_status);
        storeList = findViewById(R.id.playback_store_list);
        storeCheck = findViewById(R.id.button_store_check);
        autoExpandBlock = findViewById(R.id.playback_autoexpand_block);
        autoExpandGroup = findViewById(R.id.playback_autoexpand_group);

        findViewById(R.id.button_playback_prefs).setOnClickListener(v ->
                PlaybackPrefsDialog.show(getSupportFragmentManager(), service));

        addRadio(vuGroup, getString(R.string.appliance_vu_meter_on), true).setLayoutParams(weighted());
        addRadio(vuGroup, getString(R.string.appliance_vu_meter_off), false).setLayoutParams(weighted());
        vuGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Boolean on = (Boolean) checkedTag(group, id);
            if (on != null && on != vuEnabled) setVuMeter(on);
        });

        styleGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            String style = (String) checkedTag(group, id);
            if (style != null && !style.equals(vuStyle)) setVuStyle(style);
        });

        for (int s : AUTOEXPAND_CHOICES) {
            String label = s == 0 ? getString(R.string.appliance_autoexpand_off) : getString(R.string.appliance_seconds, s);
            addRadio(autoExpandGroup, label, s).setLayoutParams(weighted());
        }
        autoExpandGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Integer s = (Integer) checkedTag(group, id);
            if (s != null && s != autoExpand) setAutoExpand(s);
        });

        storeCheck.setOnClickListener(v -> checkStore());

        loadVuMeter();
        loadVuStyle();
        loadStore(true);
        loadAutoExpand();
    }

    private static RadioGroup.LayoutParams weighted() {
        return new RadioGroup.LayoutParams(0, RadioGroup.LayoutParams.WRAP_CONTENT, 1f);
    }

    @Override
    protected void onDestroy() {
        storePoll.removeCallbacks(storePollTask);
        unbindService(serviceConnection);
        super.onDestroy();
    }

    // ── VU meters on/off ────────────────────────────────────────────────
    private void loadVuMeter() {
        load("/api/system/vu_meter", "enabled", body -> {
            vuEnabled = body.optBoolean("enabled", true);
            checkByTag(vuGroup, vuEnabled);
            vuBlock.setVisibility(View.VISIBLE);
            renderStyleBlock();
        }, () -> vuBlock.setVisibility(View.GONE));
    }

    private void setVuMeter(boolean on) {
        post("/api/system/vu_meter", json("enable", on), R.string.appliance_vu_meter_failed, body -> {
            vuEnabled = body.optBoolean("enabled", on);
            checkByTag(vuGroup, vuEnabled);
            renderStyleBlock();
            showMessage(messageOf(body, getString(R.string.appliance_vu_meter_changed)));
        }, () -> checkByTag(vuGroup, vuEnabled));
    }

    // ── VU meter style ──────────────────────────────────────────────────
    // The looks the device has installed, as it lists them — a new one shows
    // up here without an app update. Names come in both languages.
    private void loadVuStyle() {
        load("/api/system/vu_style", "style", body -> {
            vuStyle = body.optString("style", "classic");
            JSONArray styles = body.optJSONArray("styles");
            styleGroup.removeAllViews();
            styleCount = styles != null ? styles.length() : 0;
            for (int i = 0; i < styleCount; i++) {
                JSONObject st = styles.optJSONObject(i);
                if (st == null) continue;
                addRadio(styleGroup, localizedName(st), st.optString("id"));
            }
            checkByTag(styleGroup, vuStyle);
            renderStyleBlock();
        }, () -> {
            styleCount = 0;
            renderStyleBlock();
        });
    }

    private void renderStyleBlock() {
        styleBlock.setVisibility(vuEnabled && styleCount > 1 ? View.VISIBLE : View.GONE);
    }

    private void setVuStyle(String style) {
        post("/api/system/vu_style", json("style", style), R.string.appliance_vu_meter_failed, body -> {
            vuStyle = body.optString("style", style);
            checkByTag(styleGroup, vuStyle);
            showMessage(messageOf(body, getString(R.string.appliance_vu_style_changed)));
        }, () -> checkByTag(styleGroup, vuStyle));
    }

    /** `name` is { en, it, ... } on skins and store entries; falls back to English, then the id. */
    private String localizedName(JSONObject item) {
        JSONObject names = item.optJSONObject("name");
        String id = item.optString("id");
        if (names == null) return item.optString("name", id);
        // The app's own language setting, which may differ from the phone's.
        String lang = getResources().getConfiguration().getLocales().get(0).getLanguage();
        String name = names.optString(lang, "");
        if (name.isEmpty()) name = names.optString("en", "");
        return name.isEmpty() ? id : name;
    }

    // ── VU meter store ──────────────────────────────────────────────────
    // More looks published by Osmium Sound, downloaded and checked by the
    // device itself. Re-read while it checks the list or installs; a finished
    // install refreshes the styles above.
    private void loadStore(boolean markSeen) {
        storePoll.removeCallbacks(storePollTask);
        load("/api/system/vu_store", "skins", body -> {
            boolean wasBusy = storeBusy;
            boolean checking = body.optBoolean("checking", false);
            storeBusy = body.optBoolean("busy", false);
            JSONArray skins = body.optJSONArray("skins");
            int count = skins != null ? skins.length() : 0;
            JSONObject error = body.optJSONObject("error");

            if (wasBusy && !storeBusy) loadVuStyle();
            if (markSeen && count > 0 && !storeSeenSent) {
                storeSeenSent = true;
                post("/api/system/vu_store/seen", null, R.string.appliance_vu_store_failed, null, null);
            }

            String status = null;
            if (error != null) {
                status = error.optString("message", getString(R.string.appliance_vu_store_failed));
            } else if (count == 0) {
                status = getString(checking ? R.string.appliance_vu_store_loading : R.string.appliance_vu_store_empty);
            }
            storeStatus.setText(status);
            storeStatus.setVisibility(status != null ? View.VISIBLE : View.GONE);

            storeList.removeAllViews();
            for (int i = 0; i < count; i++) {
                JSONObject skin = skins.optJSONObject(i);
                if (skin != null) storeList.addView(storeItem(skin));
            }
            storeCheck.setVisibility(!checking && !storeBusy ? View.VISIBLE : View.GONE);
            storeBlock.setVisibility(View.VISIBLE);

            if (checking || storeBusy) storePoll.postDelayed(storePollTask, STORE_POLL_MS);
        }, () -> storeBlock.setVisibility(View.GONE));
    }

    private View storeItem(JSONObject skin) {
        View item = getLayoutInflater().inflate(R.layout.appliance_vu_store_item, storeList, false);
        String name = localizedName(skin);

        ImageView preview = item.findViewById(R.id.vu_store_preview);
        Bitmap bitmap = decodeDataUri(skin.optString("preview", ""));
        if (bitmap != null) {
            preview.setImageBitmap(bitmap);
            preview.setVisibility(View.VISIBLE);
        }

        TextView badge = item.findViewById(R.id.vu_store_badge);
        if (skin.optBoolean("new", false)) {
            badge.setText(R.string.appliance_vu_store_new);
            badge.setVisibility(View.VISIBLE);
        } else if (skin.optBoolean("update", false)) {
            badge.setText(R.string.appliance_vu_store_new_version);
            badge.setVisibility(View.VISIBLE);
        }

        ((TextView) item.findViewById(R.id.vu_store_name)).setText(name);
        String author = skin.optString("author", "");
        String size = String.format(Locale.getDefault(), "%.1f MB", skin.optLong("size", 0) / 1048576.0);
        ((TextView) item.findViewById(R.id.vu_store_details)).setText(author.isEmpty() ? size : author + " · " + size);

        JSONObject jobError = skin.optJSONObject("jobError");
        if (jobError != null) {
            TextView error = item.findViewById(R.id.vu_store_error);
            error.setText(jobError.optString("message", getString(R.string.appliance_vu_store_failed)));
            error.setVisibility(View.VISIBLE);
        }

        MaterialButton action = item.findViewById(R.id.vu_store_action);
        String job = skin.optString("job", "");
        if ("downloading".equals(job) || "installing".equals(job)) {
            action.setText("downloading".equals(job) ? R.string.appliance_vu_store_downloading : R.string.appliance_vu_store_installing);
            action.setEnabled(false);
        } else if (!skin.optBoolean("supported", true)) {
            action.setText(R.string.appliance_vu_store_unsupported);
            action.setEnabled(false);
        } else if (skin.optBoolean("update", false)) {
            action.setText(R.string.appliance_vu_store_update);
            action.setOnClickListener(v -> installSkin(skin.optString("id")));
        } else if (skin.optBoolean("installed", false)) {
            action.setText(R.string.appliance_vu_store_remove);
            action.setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                    .setMessage(getString(R.string.appliance_vu_store_remove_confirm, name))
                    .setNegativeButton(android.R.string.cancel, null)
                    .setPositiveButton(R.string.appliance_vu_store_remove, (d, w) -> removeSkin(skin.optString("id")))
                    .show());
        } else {
            action.setText(R.string.appliance_vu_store_install);
            action.setOnClickListener(v -> installSkin(skin.optString("id")));
        }
        return item;
    }

    private static Bitmap decodeDataUri(String uri) {
        int comma = uri.indexOf(',');
        if (!uri.startsWith("data:") || comma < 0) return null;
        try {
            byte[] bytes = Base64.decode(uri.substring(comma + 1), Base64.DEFAULT);
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private void installSkin(String id) {
        post("/api/system/vu_store/install", json("id", id), R.string.appliance_vu_store_failed,
                body -> loadStore(false), () -> loadStore(false));
    }

    private void removeSkin(String id) {
        post("/api/system/vu_store/remove", json("id", id), R.string.appliance_vu_store_failed, body -> {
            loadVuStyle();
            loadStore(false);
        }, () -> loadStore(false));
    }

    private void checkStore() {
        storeCheck.setVisibility(View.GONE);
        post("/api/system/vu_store/check", null, R.string.appliance_vu_store_failed,
                body -> loadStore(false), () -> loadStore(false));
    }

    // ── now playing opens on its own ────────────────────────────────────
    private void loadAutoExpand() {
        load("/api/system/nowplaying_autoexpand", "seconds", body -> {
            autoExpand = body.optInt("seconds", 0);
            checkByTag(autoExpandGroup, autoExpand);
            autoExpandBlock.setVisibility(View.VISIBLE);
        }, () -> autoExpandBlock.setVisibility(View.GONE));
    }

    private void setAutoExpand(int seconds) {
        post("/api/system/nowplaying_autoexpand", json("seconds", seconds), R.string.appliance_autoexpand_failed, body -> {
            autoExpand = body.optInt("seconds", seconds);
            checkByTag(autoExpandGroup, autoExpand);
            showMessage(messageOf(body, getString(R.string.appliance_autoexpand_changed)));
        }, () -> checkByTag(autoExpandGroup, autoExpand));
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, AppliancePlaybackActivity.class));
    }
}
