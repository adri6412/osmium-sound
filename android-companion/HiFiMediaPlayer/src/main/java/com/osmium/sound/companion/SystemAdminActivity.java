package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.RadioGroup;
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
 * SSH toggle, UI render resolution, panel refresh rate, VU meter toggle,
 * read-only system info, and reboot/shutdown — mirrors the Electron UI's
 * "SSH", "Display" (partial), "System Info" and "System Controls" sections
 * (kept on one screen since each is small). All calls go through
 * ApplianceHttpClient's /api/system/* proxy routes on sources_server.py.
 */
public class SystemAdminActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private SwitchMaterial sshSwitch;
    private TextView sshLogin;
    private SwitchMaterial displayModeSwitch;
    private RadioGroup uiResolutionGroup;
    private View uiRefreshBlock;
    private RadioGroup uiRefreshGroup;
    private TextView uiRefreshUnsupported;
    private SwitchMaterial vuMeterSwitch;
    private TextView systemInfoText;
    private ProgressBar progressBar;
    private TextView messageView;
    private boolean suppressSshEvent;
    private boolean suppressDisplayModeEvent;
    private boolean suppressUiResolutionEvent;
    private boolean suppressUiRefreshEvent;
    private boolean suppressVuMeterEvent;

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
        sshLogin = findViewById(R.id.ssh_login);
        displayModeSwitch = findViewById(R.id.switch_display_mode);
        uiResolutionGroup = findViewById(R.id.ui_resolution_group);
        uiRefreshBlock = findViewById(R.id.ui_refresh_block);
        uiRefreshGroup = findViewById(R.id.ui_refresh_group);
        uiRefreshUnsupported = findViewById(R.id.ui_refresh_unsupported);
        vuMeterSwitch = findViewById(R.id.switch_vu_meter);
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

        // UI render resolution and the animated VU meter are pure rendering
        // choices with no OS action, but worth reaching remotely — same
        // rationale as display mode, mirrors admin-webui's Settings.vue.
        uiResolutionGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (!suppressUiResolutionEvent) setUiResolution(uiResolutionIdToMode(checkedId));
        });
        vuMeterSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!suppressVuMeterEvent) setVuMeter(checked);
        });

        // Panel refresh rate (native <-> low-power): applies live on the
        // appliance, no session restart. Switching down asks first, like
        // admin-webui does — this phone isn't the screen being changed, so
        // there's no keep-or-revert countdown here (that exists only in the
        // on-screen Settings, where an unconfirmed low-refresh switch could
        // leave a degraded screen behind with no visible way back).
        uiRefreshGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressUiRefreshEvent) return;
            if (checkedId == R.id.radio_ui_refresh_low) {
                new MaterialAlertDialogBuilder(this)
                        .setTitle(R.string.settings_ui_refresh_title)
                        .setMessage(R.string.settings_ui_refresh_confirm)
                        .setNegativeButton(android.R.string.cancel, (d, w) -> checkUiRefresh("native"))
                        .setOnCancelListener(d -> checkUiRefresh("native"))
                        .setPositiveButton(android.R.string.ok, (d, w) -> setUiRefresh("low"))
                        .show();
            } else {
                setUiRefresh("native");
            }
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
        loadUiResolution();
        loadUiRefresh();
        loadVuMeter();
        loadSystemInfo();
    }

    private static int uiResolutionModeToId(String mode) {
        if ("720".equals(mode)) return R.id.radio_ui_resolution_720;
        if ("1080".equals(mode)) return R.id.radio_ui_resolution_1080;
        if ("native".equals(mode)) return R.id.radio_ui_resolution_native;
        return R.id.radio_ui_resolution_auto;
    }

    private static String uiResolutionIdToMode(int checkedId) {
        if (checkedId == R.id.radio_ui_resolution_720) return "720";
        if (checkedId == R.id.radio_ui_resolution_1080) return "1080";
        if (checkedId == R.id.radio_ui_resolution_native) return "native";
        return "auto";
    }

    private void loadUiResolution() {
        ApplianceHttpClient.getJson("/api/system/ui_resolution", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                suppressUiResolutionEvent = true;
                uiResolutionGroup.check(uiResolutionModeToId(body.optString("mode", "auto")));
                suppressUiResolutionEvent = false;
            }

            @Override
            public void onFailure(String message) {
                // Older appliance without the ui_resolution endpoint — hide the row.
                uiResolutionGroup.setEnabled(false);
            }
        });
    }

    private void setUiResolution(String mode) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("mode", mode);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/ui_resolution", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_ui_resolution_changed)));
                } else {
                    suppressUiResolutionEvent = true;
                    uiResolutionGroup.check(uiResolutionModeToId(body.optString("mode", "auto")));
                    suppressUiResolutionEvent = false;
                    showMessage(body.optString("message", getString(R.string.settings_ui_resolution_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_ui_resolution_failed) + ": " + message);
            }
        });
    }

    /** Reflects a refresh mode in the radios without firing the change listener. */
    private void checkUiRefresh(String mode) {
        suppressUiRefreshEvent = true;
        uiRefreshGroup.check("low".equals(mode) ? R.id.radio_ui_refresh_low : R.id.radio_ui_refresh_native);
        suppressUiRefreshEvent = false;
    }

    private void loadUiRefresh() {
        ApplianceHttpClient.getJson("/api/system/ui_refresh", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!body.has("mode")) {
                    // Not the { mode, supported } shape (e.g. a pairing error
                    // body) — nothing sensible to show, keep the block hidden.
                    uiRefreshBlock.setVisibility(View.GONE);
                    return;
                }
                // 'supported' is per-unit: not every panel offers a distinct
                // low-refresh mode for its native resolution. Show the note
                // instead of a toggle that would silently do nothing.
                boolean supported = body.optBoolean("supported", true);
                uiRefreshGroup.setVisibility(supported ? View.VISIBLE : View.GONE);
                uiRefreshUnsupported.setVisibility(supported ? View.GONE : View.VISIBLE);
                checkUiRefresh(body.optString("mode", "native"));
                uiRefreshBlock.setVisibility(View.VISIBLE);
            }

            @Override
            public void onFailure(String message) {
                // Older appliance without the ui_refresh proxy route — hide the block.
                uiRefreshBlock.setVisibility(View.GONE);
            }
        });
    }

    private void setUiRefresh(String mode) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("mode", mode);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/ui_refresh", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    checkUiRefresh(body.optString("mode", mode));
                    showMessage(body.optString("message", getString(R.string.settings_ui_refresh_changed)));
                } else {
                    // api_server reports the mode still in force alongside the
                    // refusal (OTA in progress, script missing, ...): snap back.
                    checkUiRefresh(body.optString("mode", "native"));
                    showMessage(body.optString("message", getString(R.string.settings_ui_refresh_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_ui_refresh_failed) + ": " + message);
                loadUiRefresh();
            }
        });
    }

    private void loadVuMeter() {
        ApplianceHttpClient.getJson("/api/system/vu_meter", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                suppressVuMeterEvent = true;
                vuMeterSwitch.setChecked(body.optBoolean("enabled", true));
                suppressVuMeterEvent = false;
            }

            @Override
            public void onFailure(String message) {
                // Older appliance without the vu_meter endpoint — hide the row.
                vuMeterSwitch.setEnabled(false);
            }
        });
    }

    private void setVuMeter(boolean enable) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("enable", enable);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/vu_meter", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                suppressVuMeterEvent = true;
                vuMeterSwitch.setChecked(body.optBoolean("enabled", enable));
                suppressVuMeterEvent = false;
                if (!body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_system_admin_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
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
                renderSshLogin(body.optJSONObject("account"));
            }

            @Override
            public void onFailure(String message) {
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
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
                ? getString(R.string.settings_ssh_login_is, username)
                : getString(R.string.settings_ssh_no_login_app));
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
                renderSshLogin(body.optJSONObject("account"));
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
