package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.widget.EditText;
import android.widget.RadioGroup;

import org.json.JSONArray;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;

/**
 * Lists the appliance's ALSA playback devices (DACs) and lets the user pick
 * one, plus the device's name — the web admin's Settings → Audio output card.
 * Talks to api_server.py's /audio_devices, /set_audio_device and /device_name
 * via the sources_server.py proxy (see ApplianceHttpClient).
 */
public class AudioOutputActivity extends ApplianceSettingsActivity {
    private RadioGroup deviceGroup;
    private EditText nameField;
    private String currentName = "OsmiumSound";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_audio_output_title, R.layout.activity_audio_output);

        deviceGroup = findViewById(R.id.audio_device_group);
        nameField = findViewById(R.id.audio_name_field);
        findViewById(R.id.button_save_name).setOnClickListener(v -> saveName());

        loadDevices();
        loadName();
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
        deviceGroup.setOnCheckedChangeListener(null);
        deviceGroup.removeAllViews();
        if (devices == null) return;
        for (int i = 0; i < devices.length(); i++) {
            JSONObject device = devices.optJSONObject(i);
            if (device == null) continue;
            String id = device.optString("id");
            addRadio(deviceGroup, device.optString("name", id), id);
        }
        checkByTag(deviceGroup, currentId);
        deviceGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (isQuiet()) return;
            String id = (String) checkedTag(group, checkedId);
            if (id != null) applyDevice(id);
        });
    }

    private void applyDevice(String deviceId) {
        post("/api/system/audio_device", json("device", deviceId), R.string.settings_audio_output_failed,
                body -> showMessage(getString(R.string.settings_audio_output_applied)), this::loadDevices);
    }

    // ── device name ─────────────────────────────────────────────────────
    // Renames BOTH the hostname (<name>.local) and the player name together,
    // same call as the kiosk and the web admin.
    private void loadName() {
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
        post("/api/system/device_name", json("name", name), R.string.settings_multiroom_name_failed, body -> {
            currentName = body.optString("name", name);
            showMessage(messageOf(body, getString(R.string.settings_multiroom_name_saved)));
        }, null);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, AudioOutputActivity.class));
    }
}
