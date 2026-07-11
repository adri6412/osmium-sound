package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;
import android.view.View;
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
 * Lists the appliance's ALSA playback devices (DACs) and lets the user pick
 * one, mirroring the Electron UI's "Audio Output" settings section. Talks to
 * api_server.py's /audio_devices, /set_audio_device via the sources_server.py
 * proxy (see ApplianceHttpClient).
 */
public class AudioOutputActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private RadioGroup deviceGroup;
    private ProgressBar progressBar;
    private TextView messageView;
    private boolean suppressChangeEvent;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_audio_output);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.audio_output_container), false, true, false);

        deviceGroup = findViewById(R.id.audio_device_group);
        progressBar = findViewById(R.id.audio_output_progress);
        messageView = findViewById(R.id.audio_output_message);

        loadDevices();
    }

    private void loadDevices() {
        setBusy(true);
        ApplianceHttpClient.getJson("/api/system/audio_devices", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                populateDevices(body.optJSONArray("devices"), body.optString("current", "default"));
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_audio_output_failed) + ": " + message);
            }
        });
    }

    private void populateDevices(JSONArray devices, String currentId) {
        deviceGroup.removeAllViews();
        if (devices == null) return;
        suppressChangeEvent = true;
        for (int i = 0; i < devices.length(); i++) {
            JSONObject device = devices.optJSONObject(i);
            if (device == null) continue;
            String id = device.optString("id");
            RadioButton button = new RadioButton(this);
            button.setId(View.generateViewId());
            button.setText(device.optString("name", id));
            button.setTag(id);
            button.setChecked(id.equals(currentId));
            deviceGroup.addView(button);
        }
        suppressChangeEvent = false;
        deviceGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressChangeEvent) return;
            RadioButton checked = group.findViewById(checkedId);
            if (checked == null) return;
            applyDevice((String) checked.getTag());
        });
    }

    private void applyDevice(String deviceId) {
        setBusy(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("device", deviceId);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/audio_device", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (!body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_audio_output_failed)));
                } else {
                    showMessage(getString(R.string.settings_audio_output_applied));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_audio_output_failed) + ": " + message);
            }
        });
    }

    private void setBusy(boolean busy) {
        progressBar.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void showMessage(String message) {
        messageView.setText(message);
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
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
        context.startActivity(new Intent(context, AudioOutputActivity.class));
    }
}
