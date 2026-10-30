package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.RadioGroup;

import androidx.annotation.StringRes;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

/**
 * The render resolution of the on-screen interface — the resolution part of the
 * web admin's Settings → Display card, a screen of its own under Appearance to
 * match the kiosk. Talks to /api/system/ui_resolution through the
 * sources_server.py proxy; it hides itself when the appliance can't answer.
 */
public class ResolutionActivity extends ApplianceSettingsActivity {
    private RadioGroup resolutionGroup;
    private View root;
    private String resolution = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_tile_ui_resolution, R.layout.appliance_resolution);

        root = findViewById(R.id.display_resolution_group);
        resolutionGroup = findViewById(R.id.display_resolution_group);

        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_auto), "auto");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_720), "720");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_1080), "1080");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_native), "native");
        resolutionGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            String m = (String) checkedTag(group, id);
            if (m == null || m.equals(resolution)) return;
            confirm(R.string.appliance_display_confirm_resolution, () -> setResolution(m),
                    () -> checkByTag(resolutionGroup, resolution));
        });

        loadResolution();
    }

    private void confirm(@StringRes int message, Runnable onYes, Runnable onNo) {
        new MaterialAlertDialogBuilder(this)
                .setMessage(message)
                .setNegativeButton(android.R.string.cancel, (d, w) -> { if (onNo != null) onNo.run(); })
                .setOnCancelListener(d -> { if (onNo != null) onNo.run(); })
                .setPositiveButton(android.R.string.ok, (d, w) -> onYes.run())
                .show();
    }

    private void loadResolution() {
        load("/api/system/ui_resolution", "mode", body -> {
            resolution = body.optString("mode", "auto");
            checkByTag(resolutionGroup, resolution);
            root.setVisibility(View.VISIBLE);
        }, () -> showMessage(getString(R.string.settings_ui_resolution_failed)));
    }

    private void setResolution(String m) {
        post("/api/system/ui_resolution", json("mode", m), R.string.settings_ui_resolution_failed, body -> {
            resolution = body.optString("mode", m);
            checkByTag(resolutionGroup, resolution);
            showMessage(messageOf(body, getString(R.string.settings_ui_resolution_changed)));
        }, () -> checkByTag(resolutionGroup, resolution));
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, ResolutionActivity.class));
    }
}
