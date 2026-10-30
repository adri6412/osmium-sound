package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

/**
 * Read-only system info (hostname, address, platform) — split out of the web
 * admin's Settings → System card into a screen of its own, to match the kiosk's
 * System Information section. Reboot/shutdown stay on SystemAdminActivity. Reads
 * /api/system/info through the sources_server.py proxy.
 */
public class SystemInfoActivity extends ApplianceSettingsActivity {
    private TextView systemInfoText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_tile_system_info, R.layout.appliance_system_info);

        systemInfoText = findViewById(R.id.system_info_text);
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

    public static void show(Context context) {
        context.startActivity(new Intent(context, SystemInfoActivity.class));
    }
}
