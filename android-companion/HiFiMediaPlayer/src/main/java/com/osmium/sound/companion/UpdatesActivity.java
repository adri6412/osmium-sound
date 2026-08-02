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
 * (one "Check" / one "Update now" button). Each shows its currently installed
 * version, not just update availability.
 * <p>
 * Lyrion Music Server is deliberately NOT here: it is third-party software
 * with its own release cadence, managed from Settings → Lyrion Music Server
 * (MultiroomActivity) together with the internal/external choice.
 * <p>
 * "Update now" POSTs /api/system/updates/apply_all and then only *watches*:
 * the appliance writes a plan to persistent storage and walks it to the end
 * itself (System → OS → UI, see hifi-update-runner.sh). This used to be a
 * chain of per-component applies driven from here, which broke whenever the
 * update dropped the connection — and it always does: System restarts
 * hifi-api, OS may reboot the box, UI restarts the kiosk. Losing the
 * connection now costs nothing; {@link #resumePlan()} re-attaches to a run
 * still in progress when the screen is reopened. An appliance too old to know
 * the endpoint falls back to {@link #applyCoreLegacy()}.
 */
public class UpdatesActivity extends AppCompatActivity {
    private static final long POLL_INTERVAL_MS = 2500;
    /**
     * Budget for a whole sequenced plan: up to three bundles to download,
     * verify and apply, plus the reboot an OS payload may ask for. Generous on
     * purpose — giving up early is what used to make a run that was still
     * progressing look failed.
     */
    private static final long PLAN_TIMEOUT_MS = 1_200_000;

    private final ThemeManager mThemeManager = new ThemeManager();
    private final Handler pollHandler = new Handler(Looper.getMainLooper());
    private boolean destroyed;

    private RadioGroup channelGroup;
    private boolean suppressChannelEvent;

    private TextView versionUi, versionSystem, versionOs;
    private TextView coreStatus;
    private MaterialButton applyCoreButton;
    private ProgressBar coreProgress;

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
        coreStatus = findViewById(R.id.core_status);
        applyCoreButton = findViewById(R.id.button_apply_core);
        coreProgress = findViewById(R.id.core_progress);

        channelGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressChannelEvent) return;
            setChannel(checkedId == R.id.channel_dev ? "dev" : "prod");
        });

        findViewById(R.id.button_check_core).setOnClickListener(v -> checkCore());
        applyCoreButton.setOnClickListener(v -> applyCore());

        loadChannel();
        checkCore();
        resumePlan();
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
     * Hands the whole update to the appliance, which sequences it itself
     * (System → OS → UI) from a plan it persists to disk. That matters most
     * here: of the three clients this is the one furthest from the appliance,
     * and every step of an update drops the connection — System restarts
     * hifi-api, OS may reboot the box, UI restarts the kiosk. When the phone
     * drove the sequence, any of those could end it early and leave components
     * stale. Now losing the connection (or closing the app) costs nothing: the
     * appliance finishes on its own and we just re-attach to the progress.
     */
    private void applyCore() {
        setCoreBusy(true);
        applyCoreButton.setVisibility(View.GONE);
        setCoreStatus(getString(R.string.settings_updates_applying));
        ApplianceHttpClient.postJson("/api/system/updates/apply_all", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (destroyed) return;
                if (body.optBoolean("started", false)) {
                    pollPlan(System.currentTimeMillis());
                } else {
                    setCoreStatus(body.optString("message", getString(R.string.settings_updates_start_failed)));
                    setCoreBusy(false);
                    checkCore();
                }
            }

            @Override
            public void onFailure(String message) {
                if (destroyed) return;
                // Either there is no such endpoint (an appliance still running
                // an api_server without the sequencer) or we simply lost the
                // answer to a request that did go through. Ask before assuming:
                // falling back to the per-component chain on top of a plan that
                // is already running would have two updaters racing.
                ApplianceHttpClient.getJson("/api/system/updates/status", new ApplianceHttpClient.JsonCallback() {
                    @Override
                    public void onSuccess(JSONObject body) {
                        if (destroyed) return;
                        if ("running".equals(body.optString("state", "idle"))) {
                            pollPlan(System.currentTimeMillis());
                        } else {
                            applyCoreLegacy();
                        }
                    }

                    @Override
                    public void onFailure(String m) {
                        if (destroyed) return;
                        applyCoreLegacy();
                    }
                });
            }
        });
    }

    /**
     * Follows the appliance-side plan to its end. A failed request is expected
     * mid-plan — the API restarts and the box may reboot — so failures are
     * retried rather than treated as the final word; the plan is on persistent
     * storage and the appliance resumes it after a reboot on its own.
     */
    private void pollPlan(long startTime) {
        if (destroyed) return;
        pollHandler.postDelayed(() -> {
            if (destroyed) return;
            ApplianceHttpClient.getJson("/api/system/updates/status", new ApplianceHttpClient.JsonCallback() {
                @Override
                public void onSuccess(JSONObject body) {
                    if (destroyed) return;
                    String state = body.optString("state", "idle");
                    String message = body.optString("message", "");
                    int progress = body.optInt("overall_progress", -1);

                    if ("finished".equals(state)) {
                        setCoreStatus(getString(R.string.settings_updates_all_done));
                        setCoreBusy(false);
                        dismissPlan();
                        checkCore();
                        return;
                    }
                    if ("error".equals(state) || "interrupted".equals(state)) {
                        String text = message.isEmpty()
                                ? getString(R.string.settings_updates_update_error) : message;
                        Toast.makeText(UpdatesActivity.this, text, Toast.LENGTH_LONG).show();
                        setCoreStatus(text);
                        setCoreBusy(false);
                        dismissPlan();
                        checkCore();
                        return;
                    }
                    if (!"idle".equals(state)) {
                        setCoreStatus((message.isEmpty() ? state : message)
                                + (progress >= 0 ? " (" + progress + "%)" : ""));
                    }
                    if (System.currentTimeMillis() - startTime > PLAN_TIMEOUT_MS) {
                        setCoreStatus(getString(R.string.settings_updates_timeout));
                        setCoreBusy(false);
                        checkCore();
                        return;
                    }
                    pollPlan(startTime);
                }

                @Override
                public void onFailure(String message) {
                    if (destroyed) return;
                    setCoreStatus(getString(R.string.settings_updates_reconnecting));
                    if (System.currentTimeMillis() - startTime > PLAN_TIMEOUT_MS) {
                        setCoreStatus(getString(R.string.settings_updates_timeout));
                        setCoreBusy(false);
                        checkCore();
                        return;
                    }
                    pollPlan(startTime);
                }
            });
        }, POLL_INTERVAL_MS);
    }

    /** Lets the appliance drop a plan whose outcome we've already shown. */
    private void dismissPlan() {
        ApplianceHttpClient.postJson("/api/system/updates/dismiss", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
            }

            @Override
            public void onFailure(String message) {
            }
        });
    }

    /**
     * Re-attaches to a plan that is already running (or that finished while the
     * app was closed) — called when the screen opens. Without it, an update
     * started from here and interrupted by a reboot would look like nothing
     * had ever happened.
     */
    private void resumePlan() {
        ApplianceHttpClient.getJson("/api/system/updates/status", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (destroyed) return;
                if (!"running".equals(body.optString("state", "idle"))) return;
                setCoreBusy(true);
                applyCoreButton.setVisibility(View.GONE);
                setCoreStatus(getString(R.string.settings_updates_applying));
                pollPlan(System.currentTimeMillis());
            }

            @Override
            public void onFailure(String message) {
            }
        });
    }

    /**
     * Pre-sequencer fallback, in the same order the appliance uses: System →
     * OS → UI. Carries the limitation the sequencer removes — if the OS step
     * reboots, the UI step is never applied.
     */
    private void applyCoreLegacy() {
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


    private void setCoreBusy(boolean busy) {
        coreProgress.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void setCoreStatus(String text) {
        coreStatus.setText(text);
        coreStatus.setVisibility(View.VISIBLE);
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
