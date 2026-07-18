package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
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
 * (one "Check" / one "Update now" button, applied in sequence System → OS →
 * UI — see applyAllUpdates() in Settings.jsx — System doesn't tear down the
 * live session, UI restarts the kiosk so it goes last), while Lyrion Music
 * Server has its own separate check/apply (Electron's "Advanced" sub-section).
 * Each shows its currently installed version, not just update availability.
 * <p>
 * Applying System/OS makes the appliance restart hifi-api (System) or reboot
 * outright (OS, when apply.sh leaves a REBOOT marker) — a dropped connection
 * partway through is expected, not a failure, so each step polls
 * /api/system/updates/{kind}/status until it reports "done"/"error" instead
 * of treating the single apply POST (or a transient poll failure) as the
 * final word.
 */
public class UpdatesActivity extends AppCompatActivity {
    private static final long POLL_INTERVAL_MS = 2500;

    private final ThemeManager mThemeManager = new ThemeManager();
    private final Handler pollHandler = new Handler(Looper.getMainLooper());
    private boolean destroyed;

    private RadioGroup channelGroup;
    private boolean suppressChannelEvent;

    private TextView versionUi, versionSystem, versionOs, versionLyrion;
    private TextView coreStatus, lyrionStatus;
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
        coreStatus = findViewById(R.id.core_status);
        lyrionStatus = findViewById(R.id.lyrion_status);
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

    /** Notified as an apply-and-poll step progresses; see {@link #startApply}. */
    private interface UpdatePhase {
        void onStatus(String text);
        void onDone();
        void onFailed(String message);
    }

    /**
     * Applies in the same order as the Electron UI's applyAllUpdates(): System
     * → OS → UI (System doesn't tear down a live session; OS reboots only on a
     * real change; UI restarts the kiosk so it's last/terminal).
     */
    private void applyCore() {
        setCoreBusy(true);
        applyCoreButton.setVisibility(View.GONE);
        setCoreStatus(getString(R.string.settings_updates_applying));
        runCoreStep("system", getString(R.string.settings_updates_system), 90_000, false, () ->
                runCoreStep("os", getString(R.string.settings_updates_os), 180_000, true, () ->
                        runCoreStep("app", getString(R.string.settings_updates_ui), 60_000, false, () -> {
                            setCoreStatus(getString(R.string.settings_updates_all_done));
                            checkCore();
                        })));
    }

    private void runCoreStep(String kind, String phaseLabel, long timeoutMs, boolean osRebootAware, Runnable onDone) {
        startApply(kind, phaseLabel, timeoutMs, osRebootAware, new UpdatePhase() {
            @Override
            public void onStatus(String text) {
                setCoreStatus(text);
            }

            @Override
            public void onDone() {
                onDone.run();
            }

            @Override
            public void onFailed(String message) {
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_LONG).show();
                setCoreStatus(message);
                // Re-check rather than assume: the step may have actually
                // finished server-side despite the dropped/timed-out connection.
                checkCore();
            }
        });
    }

    /**
     * POSTs {@code /api/system/updates/<kind>/apply} (fire-and-forget on the
     * appliance, via systemd-run) then polls {@code .../status} until it
     * reports "done" or "error". A dropped connection while polling is
     * expected mid-update — System restarts hifi-api itself, OS may reboot
     * the whole box — so transient poll failures are retried, not treated as
     * a finished (successful or failed) update.
     */
    private void startApply(String kind, String phaseLabel, long timeoutMs, boolean osRebootAware, UpdatePhase phase) {
        phase.onStatus(phaseLabel + ": " + getString(R.string.settings_updates_starting));
        ApplianceHttpClient.postJson("/api/system/updates/" + kind + "/apply", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (body.optBoolean("started", false)) {
                    pollApplyStatus(kind, phaseLabel, timeoutMs, osRebootAware, System.currentTimeMillis(), false, phase);
                } else {
                    phase.onFailed(phaseLabel + ": " + body.optString("message", getString(R.string.settings_updates_start_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                phase.onFailed(phaseLabel + ": " + message);
            }
        });
    }

    private void pollApplyStatus(String kind, String phaseLabel, long timeoutMs, boolean osRebootAware,
                                  long startTime, boolean sawRestarting, UpdatePhase phase) {
        if (destroyed) return;
        pollHandler.postDelayed(() -> {
            if (destroyed) return;
            ApplianceHttpClient.getJson("/api/system/updates/" + kind + "/status", new ApplianceHttpClient.JsonCallback() {
                @Override
                public void onSuccess(JSONObject body) {
                    if (destroyed) return;
                    String state = body.optString("state", "idle");
                    String message = body.optString("message", "");
                    int progress = body.optInt("progress", -1);
                    boolean nowRestarting = sawRestarting || "restarting".equals(state);

                    if ("done".equals(state)) {
                        phase.onDone();
                        return;
                    }
                    if ("error".equals(state)) {
                        phase.onFailed(phaseLabel + ": " + (message.isEmpty() ? getString(R.string.settings_updates_update_error) : message));
                        return;
                    }
                    if ("idle".equals(state)) {
                        if (osRebootAware && sawRestarting) {
                            // The status file lives on tmpfs and is wiped by the
                            // reboot this OS update triggered; seeing "idle" again
                            // right after "restarting" means it came back up, i.e.
                            // the update (and reboot) succeeded.
                            phase.onDone();
                            return;
                        }
                    } else {
                        phase.onStatus(phaseLabel + ": " + (message.isEmpty() ? state : message)
                                + (progress >= 0 ? " (" + progress + "%)" : ""));
                    }

                    if (System.currentTimeMillis() - startTime > timeoutMs) {
                        phase.onFailed(phaseLabel + ": " + getString(R.string.settings_updates_timeout));
                        return;
                    }
                    pollApplyStatus(kind, phaseLabel, timeoutMs, osRebootAware, startTime, nowRestarting, phase);
                }

                @Override
                public void onFailure(String message) {
                    if (destroyed) return;
                    phase.onStatus(phaseLabel + ": " + getString(R.string.settings_updates_reconnecting));
                    if (System.currentTimeMillis() - startTime > timeoutMs) {
                        phase.onFailed(phaseLabel + ": " + getString(R.string.settings_updates_timeout));
                        return;
                    }
                    pollApplyStatus(kind, phaseLabel, timeoutMs, osRebootAware, startTime, sawRestarting, phase);
                }
            });
        }, POLL_INTERVAL_MS);
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
        setLyrionStatus(getString(R.string.settings_updates_applying));
        startApply("lyrion", getString(R.string.settings_updates_lyrion), 90_000, false, new UpdatePhase() {
            @Override
            public void onStatus(String text) {
                setLyrionStatus(text);
            }

            @Override
            public void onDone() {
                lyrionProgress.setVisibility(View.GONE);
                setLyrionStatus(getString(R.string.settings_updates_all_done));
                checkLyrion();
            }

            @Override
            public void onFailed(String message) {
                Toast.makeText(UpdatesActivity.this, message, Toast.LENGTH_LONG).show();
                setLyrionStatus(message);
                lyrionProgress.setVisibility(View.GONE);
                checkLyrion();
            }
        });
    }

    private void setCoreBusy(boolean busy) {
        coreProgress.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void setCoreStatus(String text) {
        coreStatus.setText(text);
        coreStatus.setVisibility(View.VISIBLE);
    }

    private void setLyrionStatus(String text) {
        lyrionStatus.setText(text);
        lyrionStatus.setVisibility(View.VISIBLE);
    }

    @Override
    public void onResume() {
        super.onResume();
        mThemeManager.onResume(this);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        pollHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
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
