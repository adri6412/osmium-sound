package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
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

import org.json.JSONArray;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Player rename + "follow another device's Lyrion server" controls, mirroring
 * the Electron UI's Settings → Multiroom section. Every Osmium Sound device
 * runs its own local Lyrion Music Server by default, so two devices never see
 * each other as syncable players until one of them is pointed at the other's
 * server (api_server.py's /player_name, /lms_role, /discover_lms, reached via
 * sources_server.py's /api/system/* proxy — see ApplianceHttpClient).
 */
public class MultiroomActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private EditText nameField;
    private RadioGroup roleGroup;
    private View followSection;
    private RadioGroup discoveredGroup;
    private TextView discoveredLabel;
    private EditText hostField;
    private ProgressBar progressBar;
    private TextView messageView;
    private boolean suppressRoleEvent;
    private boolean suppressDiscoveredEvent;
    private String currentName = "OsmiumSound";

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
        followSection = findViewById(R.id.multiroom_follow_section);
        discoveredGroup = findViewById(R.id.multiroom_discovered_group);
        discoveredLabel = findViewById(R.id.multiroom_discovered_label);
        hostField = findViewById(R.id.multiroom_host_field);
        progressBar = findViewById(R.id.multiroom_progress);
        messageView = findViewById(R.id.multiroom_message);

        findViewById(R.id.button_save_name).setOnClickListener(v -> saveName());
        findViewById(R.id.button_scan).setOnClickListener(v -> scan());
        findViewById(R.id.button_apply_host).setOnClickListener(v -> applyHost());

        roleGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressRoleEvent) return;
            boolean follow = checkedId == R.id.radio_role_follow;
            followSection.setVisibility(follow ? View.VISIBLE : View.GONE);
            if (!follow) applyRole("local", null);
        });

        loadPlayerName();
        loadRole();
    }

    private void loadPlayerName() {
        ApplianceHttpClient.playerName(new ApplianceHttpClient.JsonCallback() {
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
        ApplianceHttpClient.setPlayerName(name, new ApplianceHttpClient.JsonCallback() {
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
                followSection.setVisibility(follow ? View.VISIBLE : View.GONE);
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
