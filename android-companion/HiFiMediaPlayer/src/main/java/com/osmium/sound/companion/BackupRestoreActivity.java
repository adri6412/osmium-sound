package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.Nullable;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;

/**
 * The web admin's Settings → Backup &amp; restore card, over sources_server.py's
 * /api/backup* and /api/restore* routes (pairing token): an optional
 * passphrase deciding whether credentials go in (encrypted) or not, backups
 * stored on the device (download, restore, delete), a backup downloaded on the
 * spot, a restore from a file, and the automatic weekly backup.
 * <p>
 * Backups and restores run in the background on the appliance and are
 * followed by polling their status. A finished restore reboots the device, as
 * the web admin does, so every service picks up what was written back.
 */
public class BackupRestoreActivity extends ApplianceSettingsActivity {
    private static final long POLL_MS = 1500;
    private static final int POLL_MAX = 600;

    private EditText passphraseField;
    private View createButton;
    private View downloadNowButton;
    private View scheduledBlock;
    private SwitchMaterial scheduledSwitch;
    private View listBlock;
    private TextView noneText;
    private LinearLayout list;

    private ActivityResultLauncher<String> createBackupFileLauncher;
    private ActivityResultLauncher<String[]> pickRestoreFileLauncher;
    /** Stored backup the pending CreateDocument is for; null = a fresh one. */
    private String pendingDownloadId;

    private final Handler pollHandler = new Handler(Looper.getMainLooper());
    private Runnable pollTask;
    private ZoneId deviceZone = ZoneId.systemDefault();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_backup_title, R.layout.activity_backup_restore);

        passphraseField = findViewById(R.id.backup_passphrase);
        createButton = findViewById(R.id.button_backup_create);
        downloadNowButton = findViewById(R.id.button_export_backup);
        scheduledBlock = findViewById(R.id.backup_scheduled_block);
        scheduledSwitch = findViewById(R.id.switch_backup_scheduled);
        listBlock = findViewById(R.id.backup_list_block);
        noneText = findViewById(R.id.backup_none);
        list = findViewById(R.id.backup_list);

        createBackupFileLauncher = registerForActivityResult(
                new ActivityResultContracts.CreateDocument("application/gzip"), this::onBackupFileChosen);
        pickRestoreFileLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onRestoreFileChosen);

        createButton.setOnClickListener(v -> createBackup());
        downloadNowButton.setOnClickListener(v -> download(null));
        findViewById(R.id.button_restore_backup).setOnClickListener(v ->
                pickRestoreFileLauncher.launch(new String[]{"application/gzip", "application/x-gzip", "*/*"}));
        scheduledSwitch.setOnCheckedChangeListener((btn, checked) -> {
            if (!isQuiet()) saveScheduled(checked);
        });

        // Stored backups are named by their UTC time; show it on the device's clock.
        load("/api/system/timezone", "timezone", body -> {
            try {
                deviceZone = ZoneId.of(body.optString("timezone"));
                loadBackups();
            } catch (Exception ignored) {
            }
        }, null);
        loadBackups();
    }

    @Override
    protected void onDestroy() {
        stopPolling();
        super.onDestroy();
    }

    private String passphrase() {
        return passphraseField.getText() != null ? passphraseField.getText().toString() : "";
    }

    // ── stored backups ──────────────────────────────────────────────────
    private void loadBackups() {
        load("/api/backup/list", "generations", body -> {
            JSONObject settings = body.optJSONObject("settings");
            quietly(() -> scheduledSwitch.setChecked(settings != null && settings.optBoolean("scheduled", false)));
            scheduledBlock.setVisibility(View.VISIBLE);

            JSONArray gens = body.optJSONArray("generations");
            list.removeAllViews();
            int count = gens != null ? gens.length() : 0;
            for (int i = 0; i < count; i++) {
                JSONObject gen = gens.optJSONObject(i);
                if (gen != null) list.addView(backupItem(gen));
            }
            noneText.setVisibility(count == 0 ? View.VISIBLE : View.GONE);
            listBlock.setVisibility(View.VISIBLE);
        }, () -> {
            // An appliance without stored backups yet: the download/restore
            // buttons still work against the older routes.
            scheduledBlock.setVisibility(View.GONE);
            listBlock.setVisibility(View.GONE);
        });
    }

    private View backupItem(JSONObject gen) {
        View item = getLayoutInflater().inflate(R.layout.appliance_backup_item, list, false);
        String id = gen.optString("id");

        StringBuilder title = new StringBuilder(formatStamp(id));
        if (gen.optBoolean("encrypted", false)) {
            title.append("  🔒 ").append(getString(R.string.appliance_backup_encrypted));
        }
        String trigger = gen.optString("trigger", "");
        if (!trigger.isEmpty() && !"manual".equals(trigger)) title.append("  ·  ").append(trigger);
        ((TextView) item.findViewById(R.id.backup_item_title)).setText(title);

        List<String> categories = new ArrayList<>();
        JSONArray cats = gen.optJSONArray("categories");
        for (int i = 0; cats != null && i < cats.length(); i++) categories.add(cats.optString(i));
        String size = formatSize(gen.optLong("size", 0));
        String details = String.join(", ", categories);
        if (!size.isEmpty()) details = details.isEmpty() ? size : details + " · " + size;
        ((TextView) item.findViewById(R.id.backup_item_details)).setText(details);

        item.findViewById(R.id.backup_item_download).setOnClickListener(v -> download(id));
        item.findViewById(R.id.backup_item_restore).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setMessage(R.string.appliance_backup_restore_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.appliance_backup_restore_this, (d, w) -> restoreStored(id))
                .show());
        item.findViewById(R.id.backup_item_delete).setOnClickListener(v -> new MaterialAlertDialogBuilder(this)
                .setMessage(R.string.appliance_backup_delete_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.appliance_backup_delete, (d, w) -> deleteStored(id))
                .show());
        return item;
    }

    /** Ids are UTC timestamps, YYYYMMDD-HHMMSS (hifi_backup.py). */
    private String formatStamp(String id) {
        try {
            LocalDateTime utc = LocalDateTime.parse(id, DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.US));
            return utc.atOffset(ZoneOffset.UTC).atZoneSameInstant(deviceZone)
                    .format(DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm", Locale.US));
        } catch (Exception e) {
            return id;
        }
    }

    private static String formatSize(long bytes) {
        if (bytes <= 0) return "";
        return bytes >= 1048576
                ? String.format(Locale.getDefault(), "%.1f MB", bytes / 1048576.0)
                : Math.max(1, Math.round(bytes / 1024.0)) + " kB";
    }

    private void deleteStored(String id) {
        setBusy(true);
        ApplianceHttpClient.deleteJson("/api/backup/" + id, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (!body.optBoolean("success", true)) {
                    showMessage(messageOf(body, getString(R.string.settings_system_admin_failed)));
                }
                loadBackups();
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_system_admin_failed) + ": " + message);
            }
        });
    }

    private void saveScheduled(boolean on) {
        post("/api/backup/settings", json("scheduled", on), R.string.appliance_backup_settings_failed,
                body -> quietly(() -> scheduledSwitch.setChecked(body.optBoolean("scheduled", on))),
                this::loadBackups);
    }

    // ── create ──────────────────────────────────────────────────────────
    private void createBackup() {
        setWorking(true);
        showMessage(getString(R.string.appliance_backup_working));
        ApplianceHttpClient.postJson("/api/backup/create", json("passphrase", passphrase()), new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!body.optBoolean("success", true)) {
                    setWorking(false);
                    showMessage(messageOf(body, getString(R.string.appliance_backup_create_failed)));
                    return;
                }
                poll("/api/backup/status", R.string.appliance_backup_working, R.string.appliance_backup_created,
                        R.string.appliance_backup_create_failed, done -> {
                            setWorking(false);
                            loadBackups();
                        });
            }

            @Override
            public void onFailure(String message) {
                setWorking(false);
                showMessage(getString(R.string.appliance_backup_create_failed) + ": " + message);
            }
        });
    }

    private void setWorking(boolean working) {
        createButton.setEnabled(!working);
        downloadNowButton.setEnabled(!working);
        setBusy(working);
    }

    // ── download ────────────────────────────────────────────────────────
    private void download(@Nullable String id) {
        pendingDownloadId = id;
        String name = id != null ? id : LocalDateTime.now(ZoneOffset.UTC)
                .format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.US));
        createBackupFileLauncher.launch("osmium-backup-" + name + ".tar.gz");
    }

    private void onBackupFileChosen(Uri uri) {
        if (uri == null) return;
        setBusy(true);
        showMessage(getString(R.string.appliance_backup_working));
        try {
            OutputStream out = getContentResolver().openOutputStream(uri);
            if (out == null) {
                setBusy(false);
                showMessage(getString(R.string.appliance_backup_download_failed));
                return;
            }
            ApplianceHttpClient.backupDownload(pendingDownloadId, out, new ApplianceHttpClient.JsonCallback() {
                @Override
                public void onSuccess(JSONObject body) {
                    closeQuietly(out);
                    setBusy(false);
                    showMessage(getString(R.string.settings_backup_export_success));
                }

                @Override
                public void onFailure(String message) {
                    closeQuietly(out);
                    setBusy(false);
                    showMessage(getString(R.string.appliance_backup_download_failed) + ": " + message);
                }
            });
        } catch (Exception e) {
            setBusy(false);
            showMessage(getString(R.string.appliance_backup_download_failed) + ": " + e.getMessage());
        }
    }

    private static void closeQuietly(OutputStream out) {
        try {
            out.close();
        } catch (Exception ignored) {
        }
    }

    // ── restore ─────────────────────────────────────────────────────────
    private void onRestoreFileChosen(Uri uri) {
        if (uri == null) return;
        new MaterialAlertDialogBuilder(this)
                .setMessage(R.string.appliance_backup_restore_confirm)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_backup_restore_button, (d, w) -> restoreFile(uri))
                .show();
    }

    private void restoreFile(Uri uri) {
        setBusy(true);
        showMessage(getString(R.string.appliance_backup_restoring));
        ApplianceHttpClient.restoreUpload(uri, getContentResolver(), passphrase(), restoreStarted());
    }

    private void restoreStored(String id) {
        setBusy(true);
        showMessage(getString(R.string.appliance_backup_restoring));
        ApplianceHttpClient.postJson("/api/backup/" + id + "/restore", json("passphrase", passphrase()), restoreStarted());
    }

    private ApplianceHttpClient.JsonCallback restoreStarted() {
        return new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!body.optBoolean("started", false)) {
                    setBusy(false);
                    showMessage(messageOf(body, getString(R.string.settings_backup_restore_failed)));
                    loadBackups();
                    return;
                }
                poll("/api/restore/status", R.string.appliance_backup_restoring, R.string.appliance_backup_restored,
                        R.string.settings_backup_restore_failed, done -> {
                            setBusy(false);
                            if (done) {
                                // Restored network profiles, timezone, audio config and
                                // Lyrion prefs are all picked up cleanly by a reboot.
                                ApplianceHttpClient.postJson("/api/system/reboot", null, new ApplianceHttpClient.JsonCallback() {
                                    @Override
                                    public void onSuccess(JSONObject b) {
                                        showMessage(getString(R.string.appliance_backup_restored_rebooting));
                                    }

                                    @Override
                                    public void onFailure(String message) {
                                        showMessage(getString(R.string.appliance_backup_restored_rebooting));
                                    }
                                });
                            } else {
                                loadBackups();
                            }
                        });
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_backup_restore_failed) + ": " + message);
            }
        };
    }

    // ── status polling ──────────────────────────────────────────────────
    private interface Finished {
        void onFinished(boolean done);
    }

    /**
     * Follows a background job's { state, progress, message } until it is done
     * or failed. Failed requests in between are expected (a restore can restart
     * the very service answering) and just mean "ask again".
     */
    private void poll(String path, int workingRes, int doneRes, int errorRes, Finished finished) {
        stopPolling();
        final int[] rounds = {0};
        pollTask = () -> ApplianceHttpClient.getJson(path, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject s) {
                if (isFinishing()) return;
                String state = s.optString("state", "");
                String message = s.optString("message", "");
                if ("done".equals(state)) {
                    showMessage(message.isEmpty() ? getString(doneRes) : message);
                    finished.onFinished(true);
                } else if ("error".equals(state)) {
                    showMessage(message.isEmpty() ? getString(errorRes) : message);
                    finished.onFinished(false);
                } else {
                    String text = message.isEmpty() ? getString(workingRes) : message;
                    if (s.has("progress")) text += " " + s.optInt("progress", 0) + "%";
                    // Progress goes to the message line only: a toast per tick would pile up.
                    ((TextView) findViewById(R.id.appliance_message)).setText(text);
                    next();
                }
            }

            @Override
            public void onFailure(String message) {
                if (!isFinishing()) next();
            }

            private void next() {
                if (++rounds[0] < POLL_MAX) {
                    pollHandler.postDelayed(pollTask, POLL_MS);
                } else {
                    finished.onFinished(false);
                }
            }
        });
        pollHandler.postDelayed(pollTask, POLL_MS);
    }

    private void stopPolling() {
        if (pollTask != null) pollHandler.removeCallbacks(pollTask);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, BackupRestoreActivity.class));
    }
}
