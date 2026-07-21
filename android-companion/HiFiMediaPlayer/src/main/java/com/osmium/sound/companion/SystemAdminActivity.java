package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;

import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * SSH toggle, read-only system info, and reboot/shutdown — mirrors the
 * Electron UI's "SSH", "System Info" and "System Controls" sections
 * (kept on one screen since each is small). All calls go through
 * ApplianceHttpClient's /api/system/* proxy routes on sources_server.py.
 */
public class SystemAdminActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private SwitchMaterial sshSwitch;
    private SwitchMaterial displayModeSwitch;
    private TextView systemInfoText;
    private ProgressBar progressBar;
    private TextView messageView;
    private boolean suppressSshEvent;
    private boolean suppressDisplayModeEvent;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_system_admin);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.system_admin_container), false, true, false);

        sshSwitch = findViewById(R.id.switch_ssh);
        displayModeSwitch = findViewById(R.id.switch_display_mode);
        systemInfoText = findViewById(R.id.system_info_text);
        progressBar = findViewById(R.id.system_admin_progress);
        messageView = findViewById(R.id.system_admin_message);

        sshSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!suppressSshEvent) setSsh(checked);
        });

        // Display mode: switch ON = on-screen interface (gui), OFF = headless.
        // This is the only remote way to bring the screen back on a headless
        // unit, so it lives here next to the other appliance system controls.
        displayModeSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!suppressDisplayModeEvent) setDisplayMode(checked ? "gui" : "headless");
        });

        findViewById(R.id.button_reboot).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_reboot_button)
                .setMessage(R.string.settings_reboot_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_reboot_button, (d, w) -> post("/api/system/reboot"))
                .show());

        findViewById(R.id.button_shutdown).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_shutdown_button)
                .setMessage(R.string.settings_shutdown_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_shutdown_button, (d, w) -> post("/api/system/shutdown"))
                .show());

        loadSshStatus();
        loadDisplayMode();
        loadSystemInfo();
    }

    private void loadDisplayMode() {
        ApplianceHttpClient.getJson("/api/system/display_mode", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                suppressDisplayModeEvent = true;
                displayModeSwitch.setChecked(!"headless".equals(body.optString("mode", "gui")));
                suppressDisplayModeEvent = false;
            }

            @Override
            public void onFailure(String message) {
                // Older appliance without the display_mode endpoint — hide the row.
                displayModeSwitch.setEnabled(false);
            }
        });
    }

    private void setDisplayMode(String mode) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("mode", mode);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/display_mode", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                showMessage(body.optString("message", getString(R.string.settings_display_mode_changed)));
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void loadSshStatus() {
        ApplianceHttpClient.getJson("/api/system/ssh", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                suppressSshEvent = true;
                sshSwitch.setEnabled(body.optBoolean("available", true));
                sshSwitch.setChecked(body.optBoolean("enabled", false));
                suppressSshEvent = false;
                if (!body.optBoolean("available", true)) {
                    showMessage(getString(R.string.settings_ssh_unavailable));
                }
            }

            @Override
            public void onFailure(String message) {
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void setSsh(boolean enable) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("enable", enable);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/ssh", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                suppressSshEvent = true;
                sshSwitch.setChecked(body.optBoolean("enabled", enable));
                suppressSshEvent = false;
                // Always surface the message, not just on failure: when enabling,
                // the appliance's response carries the default-password warning
                // (mirrors the Electron kiosk UI's behavior in Settings.jsx).
                if (!body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_system_admin_failed)));
                } else {
                    String message = body.optString("message", "");
                    if (!message.isEmpty()) showMessage(message);
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void loadSystemInfo() {
        ApplianceHttpClient.getJson("/api/system/info", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                String text = getString(R.string.settings_system_info_hostname) + ": " + body.optString("hostname", "-") + "\n"
                        + getString(R.string.settings_system_info_ip) + ": " + body.optString("local_ip", "-") + "\n"
                        + getString(R.string.settings_system_info_platform) + ": " + body.optString("platform", "-")
                        + " (" + body.optString("arch", "-") + ")";
                systemInfoText.setText(text);
            }

            @Override
            public void onFailure(String message) {
                systemInfoText.setText(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void post(String path) {
        setBusy(true);
        ApplianceHttpClient.postJson(path, null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                showMessage(body.optString("message", ""));
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void setBusy(boolean busy) {
        progressBar.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void showMessage(String message) {
        messageView.setText(message);
        if (!message.isEmpty()) {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        mThemeManager.onResume(this);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, SystemAdminActivity.class));
    }
}
