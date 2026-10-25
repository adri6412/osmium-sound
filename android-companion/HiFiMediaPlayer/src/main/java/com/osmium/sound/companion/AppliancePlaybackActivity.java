package com.osmium.sound.companion;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.IBinder;
import android.view.View;
import android.widget.RadioGroup;

import com.osmium.sound.companion.dialog.PlaybackPrefsDialog;
import com.osmium.sound.companion.service.ISqueezeService;
import com.osmium.sound.companion.service.SqueezeService;

/**
 * The web admin's Settings → Playback card (admin-webui Settings.vue): track
 * transitions / ReplayGain / fixed volume (the existing PlaybackPrefsDialog),
 * and how soon the device's screen opens "now playing" on its own. The animated
 * VU meters, their style and the VU meter store now live on their own screen
 * under Appearance (VuMetersActivity), matching the kiosk.
 */
public class AppliancePlaybackActivity extends ApplianceSettingsActivity {
    private static final int[] AUTOEXPAND_CHOICES = {0, 3, 5, 10, 15};

    private View autoExpandBlock;
    private RadioGroup autoExpandGroup;

    private int autoExpand;

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

        autoExpandBlock = findViewById(R.id.playback_autoexpand_block);
        autoExpandGroup = findViewById(R.id.playback_autoexpand_group);

        findViewById(R.id.button_playback_prefs).setOnClickListener(v ->
                PlaybackPrefsDialog.show(getSupportFragmentManager(), service));

        for (int s : AUTOEXPAND_CHOICES) {
            String label = s == 0 ? getString(R.string.appliance_autoexpand_off) : getString(R.string.appliance_seconds, s);
            addRadio(autoExpandGroup, label, s).setLayoutParams(weighted());
        }
        autoExpandGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Integer s = (Integer) checkedTag(group, id);
            if (s != null && s != autoExpand) setAutoExpand(s);
        });

        loadAutoExpand();
    }

    private static RadioGroup.LayoutParams weighted() {
        return new RadioGroup.LayoutParams(0, RadioGroup.LayoutParams.WRAP_CONTENT, 1f);
    }

    @Override
    protected void onDestroy() {
        unbindService(serviceConnection);
        super.onDestroy();
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
