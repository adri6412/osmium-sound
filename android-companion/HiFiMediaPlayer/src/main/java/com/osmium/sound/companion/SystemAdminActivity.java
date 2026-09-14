package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

/**
 * Read-only system info plus reboot/shutdown — the web admin's Settings →
 * System card, minus factory reset and the support bundle, which stay on the
 * appliance's screen and the web admin (a pairing token is all that
 * authenticates this app). SSH moved to ServicesActivity and the screen
 * settings to DisplayActivity, matching the web admin's sections. All calls go
 * through ApplianceHttpClient's /api/system/* proxy routes on sources_server.py.
 */
public class SystemAdminActivity extends ApplianceSettingsActivity {
    private TextView systemInfoText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_system_admin_title, R.layout.activity_system_admin);

        systemInfoText = findViewById(R.id.system_info_text);

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

        loadSystemInfo();
    }

    private void loadSystemInfo() {
        load("/api/system/info", null, body -> {
            String text = getString(R.string.settings_system_info_hostname) + ": " + body.optString("hostname", "-") + "\n"
                    + getString(R.string.settings_system_info_ip) + ": " + body.optString("local_ip", "-") + "\n"
                    + getString(R.string.settings_system_info_platform) + ": " + body.optString("platform", "-")
                    + " (" + body.optString("arch", "-") + ")";
            systemInfoText.setText(text);
        }, () -> systemInfoText.setText(R.string.settings_system_admin_failed));
    }

    private void postAndReport(String path) {
        post(path, null, R.string.settings_system_admin_failed, body -> showMessage(body.optString("message", "")), null);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, SystemAdminActivity.class));
    }
}
