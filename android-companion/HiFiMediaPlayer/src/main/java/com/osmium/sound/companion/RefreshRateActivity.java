package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.RadioGroup;
import android.widget.TextView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

/**
 * The screen refresh rate — the refresh part of the web admin's Settings →
 * Display card, a screen of its own under Appearance to match the kiosk. Some
 * panels have no lower mode at their native resolution; the appliance says so
 * and this screen shows it instead of an option that would do nothing. Talks to
 * /api/system/ui_refresh through the sources_server.py proxy.
 */
public class RefreshRateActivity extends ApplianceSettingsActivity {
    private RadioGroup refreshGroup;
    private TextView refreshUnsupported;
    private String refresh = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_ui_refresh_title, R.layout.appliance_refresh);

        refreshGroup = findViewById(R.id.display_refresh_group);
        refreshUnsupported = findViewById(R.id.display_refresh_unsupported);

        addRadio(refreshGroup, getString(R.string.settings_ui_refresh_native), "native");
        addRadio(refreshGroup, getString(R.string.settings_ui_refresh_low), "low");
        refreshGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            String m = (String) checkedTag(group, id);
            if (m == null || m.equals(refresh)) return;
            if ("low".equals(m)) {
                new MaterialAlertDialogBuilder(this)
                        .setMessage(R.string.settings_ui_refresh_confirm)
                        .setNegativeButton(android.R.string.cancel, (d, w) -> checkByTag(refreshGroup, refresh))
                        .setOnCancelListener(d -> checkByTag(refreshGroup, refresh))
                        .setPositiveButton(android.R.string.ok, (d, w) -> setRefresh(m))
                        .show();
            } else {
                setRefresh(m);
            }
        });

        loadRefresh();
    }

    private void loadRefresh() {
        load("/api/system/ui_refresh", "mode", body -> {
            refresh = body.optString("mode", "native");
            boolean supported = body.optBoolean("supported", true);
            refreshGroup.setVisibility(supported ? View.VISIBLE : View.GONE);
            refreshUnsupported.setVisibility(supported ? View.GONE : View.VISIBLE);
            checkByTag(refreshGroup, refresh);
        }, () -> showMessage(getString(R.string.settings_ui_refresh_failed)));
    }

    private void setRefresh(String m) {
        post("/api/system/ui_refresh", json("mode", m), R.string.settings_ui_refresh_failed, body -> {
            refresh = body.optString("mode", m);
            checkByTag(refreshGroup, refresh);
            showMessage(messageOf(body, getString(R.string.settings_ui_refresh_changed)));
        }, () -> {
            // The appliance reports the mode still in force with a refusal.
            checkByTag(refreshGroup, refresh);
            loadRefresh();
        });
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, RefreshRateActivity.class));
    }
}
