package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.MenuItem;
import android.view.View;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.button.MaterialButton;

import org.json.JSONArray;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Player rename + which Lyrion Music Server this device uses, mirroring the
 * kiosk's and web admin's Settings → Lyrion Music Server section.
 *
 * The choice is presented as internal (this device runs the server) vs external
 * (one already on the network); the wire values stay "local"/"follow" because
 * that is what api_server.set_lms_role writes into squeezelite's -s argument.
 * Every Osmium Sound device runs its own server by default, so two devices
 * never see each other as syncable players until one is pointed at the other's.
 *
 * On the internal side this screen also owns the Lyrion build: installed
 * version, release/nightly/dev channel and install-update. That deliberately
 * does NOT live on the Updates screen — Updates covers the appliance's own
 * software, Lyrion is third-party with its own release cadence.
 *
 * Everything goes through sources_server.py's /api/system/* proxy; see
 * ApplianceHttpClient.
 */
public class MultiroomActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private EditText nameField;
    private RadioGroup roleGroup;
    private View internalSection;
    private View followSection;
    private RadioGroup discoveredGroup;
    private TextView discoveredLabel;
    private EditText hostField;
    private ProgressBar progressBar;
    private TextView messageView;
    private boolean suppressRoleEvent;
    private boolean suppressDiscoveredEvent;
    private String currentName = "OsmiumSound";

    // Internal-server (Lyrion build) state.
    private View channelSection;
    private RadioGroup channelGroup;
    private TextView channelWarning;
    private TextView installedVersion;
    private TextView lyrionStatus;
    private ProgressBar lyrionProgress;
    private MaterialButton installButton;
    private boolean suppressChannelEvent;
    private String currentChannel;          // null ⇒ appliance has no channel support
    private JSONObject lyrionChannels;      // { release|nightly|dev: { version, url } }
    private String installedLyrion = "";
    private boolean installing;
    private final Handler pollHandler = new Handler(Looper.getMainLooper());
    private Runnable pollTask;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_multiroom);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.multiroom_container), false, true, false);

        nameField = findViewById(R.id.multiroom_name_field);
        roleGroup = findViewById(R.id.multiroom_role_group);
        internalSection = findViewById(R.id.multiroom_internal_section);
        followSection = findViewById(R.id.multiroom_follow_section);
        discoveredGroup = findViewById(R.id.multiroom_discovered_group);
        discoveredLabel = findViewById(R.id.multiroom_discovered_label);
        hostField = findViewById(R.id.multiroom_host_field);
        progressBar = findViewById(R.id.multiroom_progress);
        messageView = findViewById(R.id.multiroom_message);

        channelSection = findViewById(R.id.lyrion_channel_section);
        channelGroup = findViewById(R.id.lyrion_channel_group);
        channelWarning = findViewById(R.id.lyrion_channel_warning);
        installedVersion = findViewById(R.id.lyrion_installed_version);
        lyrionStatus = findViewById(R.id.lyrion_status);
        lyrionProgress = findViewById(R.id.lyrion_progress);
        installButton = findViewById(R.id.button_install_lyrion);

        findViewById(R.id.button_save_name).setOnClickListener(v -> saveName());
        findViewById(R.id.button_scan).setOnClickListener(v -> scan());
        findViewById(R.id.button_apply_host).setOnClickListener(v -> applyHost());
        installButton.setOnClickListener(v -> installLyrion());

        roleGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressRoleEvent) return;
            boolean follow = checkedId == R.id.radio_role_follow;
            showRoleSection(follow);
            if (!follow) applyRole("local", null);
        });

        channelGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressChannelEvent) return;
            applyChannel(channelIdToName(checkedId));
        });

        loadPlayerName();
        loadRole();
        loadLyrionChannel();
        loadLyrionState();
    }

    private void showRoleSection(boolean follow) {
        followSection.setVisibility(follow ? View.VISIBLE : View.GONE);
        internalSection.setVisibility(follow ? View.GONE : View.VISIBLE);
    }

    // ── Lyrion build (internal server only) ────────────────────────────
    private static String channelIdToName(int checkedId) {
        if (checkedId == R.id.radio_channel_nightly) return "nightly";
        if (checkedId == R.id.radio_channel_dev) return "dev";
        return "release";
    }

    private static int channelNameToId(String channel) {
        if ("nightly".equals(channel)) return R.id.radio_channel_nightly;
        if ("dev".equals(channel)) return R.id.radio_channel_dev;
        return R.id.radio_channel_release;
    }

    /**
     * Feature-detect the channel endpoint: an appliance that predates it simply
     * has no picker, and that must not read as an error — the install button
     * still works and uses the single stream the old backend knows about.
     */
    private void loadLyrionChannel() {
        ApplianceHttpClient.lyrionChannel(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                String channel = body.optString("channel", "");
                if (channel.isEmpty()) return;
                currentChannel = channel;
                channelSection.setVisibility(View.VISIBLE);
                suppressChannelEvent = true;
                channelGroup.check(channelNameToId(channel));
                suppressChannelEvent = false;
                channelWarning.setVisibility("release".equals(channel) ? View.GONE : View.VISIBLE);
            }

            @Override
            public void onFailure(String message) {
                // Older appliance — leave the picker hidden, say nothing.
            }
        });
    }

    private void loadLyrionState() {
        ApplianceHttpClient.lyrionCheck(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                String current = body.optString("current", "");
                installedLyrion = (current.isEmpty() || "unknown".equals(current)) ? "" : current;
                lyrionChannels = body.optJSONObject("channels");
                renderLyrionVersions();
                String error = body.optString("error", "");
                if (!error.isEmpty()) lyrionStatus.setText(error);
            }

            @Override
            public void onFailure(String message) {
                installedVersion.setText(getString(R.string.settings_lyrion_installed,
                        getString(R.string.settings_lyrion_not_installed)));
            }
        });
    }

    private void renderLyrionVersions() {
        installedVersion.setText(getString(R.string.settings_lyrion_installed,
                installedLyrion.isEmpty()
                        ? getString(R.string.settings_lyrion_not_installed)
                        : installedLyrion));
        installButton.setText(installedLyrion.isEmpty()
                ? R.string.settings_lyrion_install
                : R.string.settings_lyrion_update);
        // Annotate each channel with the version it would install.
        applyChannelLabel(R.id.radio_channel_release, "release", R.string.settings_lyrion_channel_release);
        applyChannelLabel(R.id.radio_channel_nightly, "nightly", R.string.settings_lyrion_channel_nightly);
        applyChannelLabel(R.id.radio_channel_dev, "dev", R.string.settings_lyrion_channel_dev);
    }

    private void applyChannelLabel(int viewId, String key, int labelRes) {
        RadioButton button = findViewById(viewId);
        if (button == null) return;
        String label = getString(labelRes);
        JSONObject entry = lyrionChannels != null ? lyrionChannels.optJSONObject(key) : null;
        String version = entry != null ? entry.optString("version", "") : "";
        button.setText(version.isEmpty() ? label : label + "  ·  " + version);
    }

    private void applyChannel(String channel) {
        setBusy(true);
        ApplianceHttpClient.setLyrionChannel(channel, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    currentChannel = channel;
                    channelWarning.setVisibility("release".equals(channel) ? View.GONE : View.VISIBLE);
                    loadLyrionState();
                } else {
                    suppressChannelEvent = true;
                    channelGroup.check(channelNameToId(currentChannel));
                    suppressChannelEvent = false;
                    showMessage(body.optString("message", getString(R.string.settings_lyrion_install_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                suppressChannelEvent = true;
                channelGroup.check(channelNameToId(currentChannel));
                suppressChannelEvent = false;
                showMessage(message);
            }
        });
    }

    private void installLyrion() {
        if (installing) return;
        installing = true;
        installButton.setEnabled(false);
        lyrionProgress.setVisibility(View.VISIBLE);
        lyrionProgress.setProgress(5);
        lyrionStatus.setText(R.string.settings_lyrion_installing);
        ApplianceHttpClient.lyrionApply(currentChannel, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!body.optBoolean("started", false)) {
                    finishInstall(body.optString("message",
                            getString(R.string.settings_lyrion_install_failed)));
                    return;
                }
                pollLyrion();
            }

            @Override
            public void onFailure(String message) {
                finishInstall(message);
            }
        });
    }

    /** The install runs as a detached systemd unit; poll its status file. */
    private void pollLyrion() {
        pollTask = () -> ApplianceHttpClient.lyrionStatus(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                int progress = body.optInt("progress", -1);
                if (progress >= 0) lyrionProgress.setProgress(progress);
                String message = body.optString("message", "");
                if (!message.isEmpty()) lyrionStatus.setText(message);
                String state = body.optString("state", "");
                if ("done".equals(state)) {
                    finishInstall(null);
                    loadLyrionState();
                } else if ("error".equals(state)) {
                    finishInstall(message.isEmpty()
                            ? getString(R.string.settings_lyrion_install_failed) : message);
                } else if (installing) {
                    pollHandler.postDelayed(pollTask, 2000);
                }
            }

            @Override
            public void onFailure(String message) {
                if (installing) pollHandler.postDelayed(pollTask, 2000);
            }
        });
        pollHandler.postDelayed(pollTask, 2000);
    }

    private void finishInstall(String error) {
        installing = false;
        if (pollTask != null) pollHandler.removeCallbacks(pollTask);
        installButton.setEnabled(true);
        lyrionProgress.setVisibility(View.GONE);
        if (error != null) {
            lyrionStatus.setText(error);
            showMessage(error);
        }
    }

    @Override
    protected void onDestroy() {
        installing = false;
        if (pollTask != null) pollHandler.removeCallbacks(pollTask);
        super.onDestroy();
    }

    private void loadPlayerName() {
        ApplianceHttpClient.deviceName(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                currentName = body.optString("name", "OsmiumSound");
                nameField.setText(currentName);
            }

            @Override
            public void onFailure(String message) {
                showMessage(getString(R.string.settings_multiroom_name_failed) + ": " + message);
            }
        });
    }

    private void saveName() {
        String name = nameField.getText().toString().trim();
        if (name.isEmpty() || name.equals(currentName)) return;
        setBusy(true);
        ApplianceHttpClient.setDeviceName(name, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    currentName = name;
                    showMessage(body.optString("message", getString(R.string.settings_multiroom_name_saved)));
                } else {
                    showMessage(body.optString("message", getString(R.string.settings_multiroom_name_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_multiroom_name_failed) + ": " + message);
            }
        });
    }

    private void loadRole() {
        ApplianceHttpClient.lmsRole(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                boolean follow = "follow".equals(body.optString("mode", "local"));
                suppressRoleEvent = true;
                roleGroup.check(follow ? R.id.radio_role_follow : R.id.radio_role_local);
                suppressRoleEvent = false;
                showRoleSection(follow);
                if (follow) hostField.setText(body.optString("host", ""));
            }

            @Override
            public void onFailure(String message) {
                showMessage(getString(R.string.settings_multiroom_role_failed) + ": " + message);
            }
        });
    }

    private void scan() {
        setBusy(true);
        ApplianceHttpClient.discoverLmsServers(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                populateDiscovered(body.optJSONArray("servers"));
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_multiroom_role_failed) + ": " + message);
            }
        });
    }

    private void populateDiscovered(JSONArray servers) {
        discoveredGroup.removeAllViews();
        boolean any = servers != null && servers.length() > 0;
        discoveredLabel.setVisibility(View.VISIBLE);
        discoveredLabel.setText(any
                ? R.string.settings_multiroom_role_discovered_label
                : R.string.settings_multiroom_role_none_found);
        discoveredGroup.setVisibility(any ? View.VISIBLE : View.GONE);
        if (!any) return;

        suppressDiscoveredEvent = true;
        for (int i = 0; i < servers.length(); i++) {
            JSONObject server = servers.optJSONObject(i);
            if (server == null) continue;
            String ip = server.optString("ip");
            RadioButton button = new RadioButton(this);
            button.setId(View.generateViewId());
            button.setText(server.optString("name", ip) + " (" + ip + ")");
            button.setTag(ip);
            discoveredGroup.addView(button);
        }
        suppressDiscoveredEvent = false;
        discoveredGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressDiscoveredEvent) return;
            RadioButton checked = group.findViewById(checkedId);
            if (checked == null) return;
            String ip = (String) checked.getTag();
            hostField.setText(ip);
            applyRole("follow", ip);
        });
    }

    private void applyHost() {
        String host = hostField.getText().toString().trim();
        if (host.isEmpty()) {
            showMessage(getString(R.string.settings_multiroom_role_host_required));
            return;
        }
        applyRole("follow", host);
    }

    private void applyRole(String mode, String host) {
        setBusy(true);
        ApplianceHttpClient.setLmsRole(mode, host, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_multiroom_role_saved)));
                } else {
                    showMessage(body.optString("message", getString(R.string.settings_multiroom_role_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_multiroom_role_failed) + ": " + message);
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
        context.startActivity(new Intent(context, MultiroomActivity.class));
    }
}
