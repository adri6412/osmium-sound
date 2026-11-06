package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

/**
 * Reboot/shutdown — the system-controls part of the web admin's Settings →
 * System card, minus factory reset and the support bundle, which stay on the
 * appliance's screen and the web admin (a pairing token is all that
 * authenticates this app). Read-only system info moved to SystemInfoActivity,
 * SSH to ServicesActivity and the screen settings to DisplayActivity, matching
 * the kiosk's sections. All calls go through ApplianceHttpClient's /api/system/*
 * proxy routes on sources_server.py.
 */
public class SystemAdminActivity extends ApplianceSettingsActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_tile_system_controls, R.layout.activity_system_admin);

        findViewById(R.id.button_reboot).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_reboot_button)
                .setMessage(R.string.settings_reboot_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_reboot_button, (d, w) -> postAndReport("/api/system/reboot"))
                .show());

        findViewById(R.id.button_shutdown).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_shutdown_button)
                .setMessage(R.string.settings_shutdown_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_shutdown_button, (d, w) -> postAndReport("/api/system/shutdown"))
                .show());
    }

    private void postAndReport(String path) {
        post(path, null, R.string.settings_system_admin_failed, body -> showMessage(body.optString("message", "")), null);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, SystemAdminActivity.class));
    }
}
