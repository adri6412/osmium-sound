package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.MenuItem;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;

import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * DSP enable/disable, room-correction and crossfeed toggles, and convolution
 * filter (WAV/TXT impulse response) upload/status/removal — talks to the
 * appliance via ApplianceHttpClient (sources_server.py's /api/dsp/* routes).
 * Full parametric EQ band editing is intentionally out of scope here (the
 * appliance's local kiosk UI already has that); this screen only exposes
 * what the companion app's docs originally claimed: toggles + filter
 * upload/manage.
 */
public class DspSettingsActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private View unavailableMessage;
    private View rowEnabled, rowRoomCorrection, rowCrossfeed;
    private SwitchMaterial switchEnabled, switchRoomCorrection, switchCrossfeed;
    private TextView filterStatus;
    private View buttonUpload, buttonRemove;
    private ProgressBar progressBar;
    private TextView messageView;

    private boolean crossfeed;
    private boolean roomCorrection;
    private boolean suppressToggleEvents;

    private ActivityResultLauncher<String[]> pickFilterLauncher;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_dsp_settings);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.dsp_settings_container), false, true, false);

        unavailableMessage = findViewById(R.id.dsp_unavailable_message);
        rowEnabled = findViewById(R.id.dsp_row_enabled);
        rowRoomCorrection = findViewById(R.id.dsp_row_room_correction);
        rowCrossfeed = findViewById(R.id.dsp_row_crossfeed);
        switchEnabled = findViewById(R.id.switch_dsp_enabled);
        switchRoomCorrection = findViewById(R.id.switch_room_correction);
        switchCrossfeed = findViewById(R.id.switch_crossfeed);
        filterStatus = findViewById(R.id.dsp_filter_status);
        buttonUpload = findViewById(R.id.button_upload_filter);
        buttonRemove = findViewById(R.id.button_remove_filter);
        progressBar = findViewById(R.id.dsp_progress);
        messageView = findViewById(R.id.dsp_message);

        pickFilterLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onFilterChosen);

        switchEnabled.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) applyDsp(checked); });
        switchRoomCorrection.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) { roomCorrection = checked; applyDsp(switchEnabled.isChecked()); } });
        switchCrossfeed.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) { crossfeed = checked; applyDsp(switchEnabled.isChecked()); } });

        buttonUpload.setOnClickListener(v -> pickFilterLauncher.launch(new String[]{"audio/x-wav", "audio/wav", "text/plain", "*/*"}));
        buttonRemove.setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_dsp_filter_remove)
                .setMessage(R.string.settings_dsp_filter_remove_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> removeFilter())
                .show());

        loadStatus();
    }

    private void loadStatus() {
        setBusy(true);
        ApplianceHttpClient.dspStatus(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                applyStatusToUi(body);
                loadFilterStatus();
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_status_failed) + ": " + message);
            }
        });
    }

    private void applyStatusToUi(JSONObject status) {
        boolean available = status.optBoolean("available", false);
        unavailableMessage.setVisibility(available ? View.GONE : View.VISIBLE);
        int rowVisibility = available ? View.VISIBLE : View.GONE;
        rowEnabled.setVisibility(rowVisibility);
        rowRoomCorrection.setVisibility(rowVisibility);
        rowCrossfeed.setVisibility(rowVisibility);
        buttonUpload.setVisibility(rowVisibility);
        buttonRemove.setVisibility(rowVisibility);
        if (!available) return;

        roomCorrection = status.optBoolean("room_correction", false);
        crossfeed = status.optBoolean("crossfeed", false);

        suppressToggleEvents = true;
        switchEnabled.setChecked(status.optBoolean("enabled", false));
        switchRoomCorrection.setChecked(roomCorrection);
        switchCrossfeed.setChecked(crossfeed);
        suppressToggleEvents = false;
    }

    private void loadFilterStatus() {
        ApplianceHttpClient.firStatus(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("present", false)) {
                    filterStatus.setText(getString(R.string.settings_dsp_filter_present,
                            body.optString("filename", "?"), body.optLong("size", 0) / 1024));
                } else {
                    filterStatus.setText(R.string.settings_dsp_filter_none);
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                filterStatus.setText(R.string.settings_dsp_filter_none);
            }
        });
    }

    private void applyDsp(boolean enabled) {
        setBusy(true);
        JSONObject config = new JSONObject();
        try {
            config.put("enabled", enabled);
            config.put("crossfeed", crossfeed);
            config.put("room_correction", roomCorrection);
            config.put("bands", new org.json.JSONArray());
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.dspSet(config, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (!body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_dsp_status_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_status_failed) + ": " + message);
            }
        });
    }

    private void onFilterChosen(Uri uri) {
        if (uri == null) return;
        String filename = queryDisplayName(uri);
        setBusy(true);
        ApplianceHttpClient.firUpload(uri, getContentResolver(), filename, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                boolean success = body.optBoolean("success", false);
                showMessage(body.optString("message", ""));
                if (success) loadFilterStatus();
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_filter_upload_failed) + ": " + message);
            }
        });
    }

    private void removeFilter() {
        setBusy(true);
        ApplianceHttpClient.firDelete(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                loadFilterStatus();
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_filter_upload_failed) + ": " + message);
            }
        });
    }

    private String queryDisplayName(Uri uri) {
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (idx >= 0) {
                    String name = cursor.getString(idx);
                    if (name != null) return name;
                }
            }
        } catch (Exception ignored) {
        }
        return "room.wav";
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
        context.startActivity(new Intent(context, DspSettingsActivity.class));
    }
}
