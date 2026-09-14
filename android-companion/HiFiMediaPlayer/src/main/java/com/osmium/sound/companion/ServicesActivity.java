package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.TextView;

import com.google.android.material.switchmaterial.SwitchMaterial;

import org.json.JSONObject;

/**
 * The web admin's Settings → Services card (admin-webui Settings.vue): the
 * Tidal Connect receiver and SSH access. The SSH login itself is shown but not
 * editable here — see renderSshLogin().
 */
public class ServicesActivity extends ApplianceSettingsActivity {
    private View tidalRow;
    private SwitchMaterial tidalSwitch;
    private SwitchMaterial sshSwitch;
    private TextView sshLogin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.appliance_section_services, R.layout.appliance_services);

        tidalRow = findViewById(R.id.services_tidal_row);
        tidalSwitch = findViewById(R.id.switch_tidal);
        sshSwitch = findViewById(R.id.switch_ssh);
        sshLogin = findViewById(R.id.ssh_login);

        tidalSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!isQuiet()) setTidal(checked);
        });
        sshSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!isQuiet()) setSsh(checked);
        });

        loadTidal();
        loadSsh();
    }

    // ── Tidal Connect ───────────────────────────────────────────────────
    // Only offered where the receiver is installed, like the web admin.
    private void loadTidal() {
        load("/api/system/tidal", "available", body -> {
            boolean available = body.optBoolean("available", false);
            quietly(() -> tidalSwitch.setChecked(body.optBoolean("enabled", false)));
            tidalRow.setVisibility(available ? View.VISIBLE : View.GONE);
        }, () -> tidalRow.setVisibility(View.GONE));
    }

    private void setTidal(boolean enable) {
        post("/api/system/tidal", json("enable", enable), R.string.settings_system_admin_failed, body -> {
            quietly(() -> tidalSwitch.setChecked(body.optBoolean("enabled", enable)));
            showMessage(messageOf(body, getString(R.string.appliance_services_tidal_updated)));
        }, this::loadTidal);
    }

    // ── SSH ─────────────────────────────────────────────────────────────
    private void loadSsh() {
        load("/api/system/ssh", "enabled", body -> {
            boolean available = body.optBoolean("available", true);
            quietly(() -> {
                sshSwitch.setEnabled(available);
                sshSwitch.setChecked(body.optBoolean("enabled", false));
            });
            if (!available) showMessage(getString(R.string.settings_ssh_unavailable));
            renderSshLogin(body.optJSONObject("account"));
        }, () -> showMessage(getString(R.string.settings_system_admin_failed)));
    }

    private void setSsh(boolean enable) {
        post("/api/system/ssh", json("enable", enable), R.string.settings_system_admin_failed, body -> {
            quietly(() -> sshSwitch.setChecked(body.optBoolean("enabled", enable)));
            renderSshLogin(body.optJSONObject("account"));
            // Always surface the message: turning SSH on carries a warning.
            String message = body.optString("message", "");
            if (!message.isEmpty()) showMessage(message);
        }, this::loadSsh);
    }

    /**
     * Shows which Linux login SSH accepts, or says none exists yet. Read-only:
     * creating that login mints a user with full sudo and a pairing token is
     * all that authenticates this app, so the form lives on the appliance's own
     * screen and in the web admin (see sources_server.py's proxy list, where
     * /shell_account is deliberately absent).
     * <p>
     * `account` is absent on an appliance older than 2.5.21-dev.37 — then the
     * row simply stays hidden.
     */
    private void renderSshLogin(JSONObject account) {
        if (account == null) {
            sshLogin.setVisibility(View.GONE);
            return;
        }
        sshLogin.setVisibility(View.VISIBLE);
        String username = account.optString("username", "");
        sshLogin.setText(account.optBoolean("exists", false) && !username.isEmpty()
                ? getString(R.string.settings_ssh_login_is, username) + applianceHost()
                : getString(R.string.settings_ssh_no_login_app));
    }

    /** The address this app reaches the appliance at, to complete "ssh user@…". */
    private static String applianceHost() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        String api = preferences.getApplianceApiAddress();
        if (api == null || api.isEmpty()) return preferences.getServerAddress().host();
        int colon = api.lastIndexOf(':');
        return colon > 0 ? api.substring(0, colon) : api;
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, ServicesActivity.class));
    }
}
