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

import com.google.android.material.button.MaterialButton;

import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * OTA channel (stable/dev) + updates, mirroring the Electron UI's "Updates"
 * section: UI + System + OS are checked/applied together as a single group
 * (one "Check" / one "Update now" button, applied in sequence System → UI →
 * OS — see applyAllUpdates() in Settings.jsx), while Lyrion Music Server has
 * its own separate check/apply (Electron's "Advanced" sub-section). Each
 * shows its currently installed version, not just update availability.
 */
public class UpdatesActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private RadioGroup channelGroup;
    private boolean suppressChannelEvent;

    private TextView versionUi, versionSystem, versionOs, versionLyrion;
    private MaterialButton applyCoreButton, applyLyrionButton;
    private ProgressBar coreProgress, lyrionProgress;

    private boolean uiUpdateAvailable, systemUpdateAvailable, osUpdateAvailable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_updates);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.updates_container), false, true, false);

        channelGroup = findViewById(R.id.updates_channel_group);
        versionUi = findViewById(R.id.version_ui);
        versionSystem = findViewById(R.id.version_system);
        versionOs = findViewById(R.id.version_os);
        versionLyrion = findViewById(R.id.version_lyrion);
        applyCoreButton = findViewById(R.id.button_apply_core);
        applyLyrionButton = findViewById(R.id.button_apply_lyrion);
        coreProgress = findViewById(R.id.core_progress);
        lyrionProgress = findViewById(R.id.lyrion_progress);

        channelGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressChannelEvent) return;
            setChannel(checkedId == R.id.channel_dev ? "dev" : "prod");
        });

        findViewById(R.id.button_check_core).setOnClickListener(v -> checkCore());
        applyCoreButton.setOnClickListener(v -> applyCore());
        findViewById(R.id.button_check_lyrion).setOnClickListener(v -> checkLyrion());
        applyLyrionButton.setOnClickListener(v -> applyLyrion());

        loadChannel();
        checkCore();
        checkLyrion();
    }

    private void loadChannel() {
        ApplianceHttpClient.getJson("/api/system/ota_channel", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                suppressChannelEvent = true;
                boolean dev = "dev".equals(body.optString("channel", "prod"));
                channelGroup.check(dev ? R.id.channel_dev : R.id.channel_prod);
                suppressChannelEvent = false;
            }

            @Override
            public void onFailure(String message) {
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void setChannel(String channel) {
        JSONObject payload = new JSONObject();
        try {
            payload.put("channel", channel);
        } catch (Exception ignored) {
        }
        ApplianceHttpClient.postJson("/api/system/ota_channel", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
            }

            @Override
            public void onFailure(String message) {
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void checkCore() {
        setCoreBusy(true);
        checkOne("app", getString(R.string.settings_updates_ui), versionUi, available -> uiUpdateAvailable = available, () -> {
            checkOne("system", getString(R.string.settings_updates_system), versionSystem, available -> systemUpdateAvailable = available, () -> {
                checkOne("os", getString(R.string.settings_updates_os), versionOs, available -> osUpdateAvailable = available, () -> {
                    setCoreBusy(false);
                    applyCoreButton.setVisibility(uiUpdateAvailable || systemUpdateAvailable || osUpdateAvailable ? View.VISIBLE : View.GONE);
                });
            });
        });
    }

    private interface AvailabilityConsumer {
        void accept(boolean available);
    }

    private void checkOne(String kind, String label, TextView versionText, AvailabilityConsumer onResult, Runnable then) {
        ApplianceHttpClient.getJson("/api/system/updates/" + kind + "/check", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                boolean available = body.optBoolean("update_available", false);
                String current = body.optString("current", "?");
                String line = label + ": " + current;
                if (available) {
                    line += " → " + body.optString("latest", "?");
                } else {
                    line += " (" + getString(R.string.settings_updates_up_to_date) + ")";
                }
                versionText.setText(line);
                onResult.accept(available);
                then.run();
            }

            @Override
            public void onFailure(String message) {
                versionText.setText(label + ": " + message);
                onResult.accept(false);
                then.run();
            }
        });
    }

    /** Applies in the same order as the Electron UI's applyAllUpdates(): System → UI → OS. */
    private void applyCore() {
        setCoreBusy(true);
        applyCoreButton.setVisibility(View.GONE);
        applyOne("system", () -> applyOne("app", () -> applyOne("os", () -> setCoreBusy(false))));
    }

    private void applyOne(String kind, Runnable then) {
        ApplianceHttpClient.postJson("/api/system/updates/" + kind + "/apply", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                then.run();
            }

            @Override
            public void onFailure(String message) {
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_SHORT).show();
                then.run();
            }
        });
    }

    private void checkLyrion() {
        lyrionProgress.setVisibility(View.VISIBLE);
        ApplianceHttpClient.getJson("/api/system/updates/lyrion/check", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                lyrionProgress.setVisibility(View.GONE);
                boolean available = body.optBoolean("update_available", false);
                String line = body.optString("current", "?");
                if (available) {
                    line += " → " + body.optString("latest", "?");
                } else {
                    line += " (" + getString(R.string.settings_updates_up_to_date) + ")";
                }
                versionLyrion.setText(line);
                applyLyrionButton.setVisibility(available ? View.VISIBLE : View.GONE);
            }

            @Override
            public void onFailure(String message) {
                lyrionProgress.setVisibility(View.GONE);
                versionLyrion.setText(message);
            }
        });
    }

    private void applyLyrion() {
        lyrionProgress.setVisibility(View.VISIBLE);
        applyLyrionButton.setVisibility(View.GONE);
        ApplianceHttpClient.postJson("/api/system/updates/lyrion/apply", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                lyrionProgress.setVisibility(View.GONE);
                checkLyrion();
            }

            @Override
            public void onFailure(String message) {
                lyrionProgress.setVisibility(View.GONE);
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void setCoreBusy(boolean busy) {
        coreProgress.setVisibility(busy ? View.VISIBLE : View.GONE);
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
        context.startActivity(new Intent(context, UpdatesActivity.class));
    }
}
