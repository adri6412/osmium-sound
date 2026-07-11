package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
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

import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Exports/imports the appliance's configuration (DAC, DSP/EQ, room-correction
 * filter, music sources, OTA channel) as a tarball, via sources_server.py's
 * /api/backup and /api/restore (already LAN-reachable today, no pairing token
 * required — see ApplianceHttpClient).
 */
public class BackupRestoreActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private ProgressBar progressBar;
    private TextView messageView;

    private ActivityResultLauncher<String> createBackupFileLauncher;
    private ActivityResultLauncher<String[]> pickRestoreFileLauncher;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_backup_restore);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.backup_restore_container), false, true, false);

        progressBar = findViewById(R.id.backup_progress);
        messageView = findViewById(R.id.backup_message);

        createBackupFileLauncher = registerForActivityResult(
                new ActivityResultContracts.CreateDocument("application/gzip"), this::onBackupFileChosen);
        pickRestoreFileLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onRestoreFileChosen);

        findViewById(R.id.button_export_backup).setOnClickListener(v -> {
            String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
            createBackupFileLauncher.launch("osmium-backup-" + stamp + ".tar.gz");
        });

        findViewById(R.id.button_restore_backup).setOnClickListener(v ->
                pickRestoreFileLauncher.launch(new String[]{"application/gzip", "application/x-gzip", "*/*"}));
    }

    private void onBackupFileChosen(Uri uri) {
        if (uri == null) return;
        setBusy(true, "");
        try {
            OutputStream out = getContentResolver().openOutputStream(uri);
            if (out == null) {
                setBusy(false, getString(R.string.settings_backup_export_failed));
                return;
            }
            ApplianceHttpClient.backupDownload(out, new ApplianceHttpClient.JsonCallback() {
                @Override
                public void onSuccess(org.json.JSONObject body) {
                    closeQuietly(out);
                    setBusy(false, getString(R.string.settings_backup_export_success));
                }

                @Override
                public void onFailure(String message) {
                    closeQuietly(out);
                    setBusy(false, getString(R.string.settings_backup_export_failed) + ": " + message);
                }
            });
        } catch (Exception e) {
            setBusy(false, getString(R.string.settings_backup_export_failed) + ": " + e.getMessage());
        }
    }

    private void onRestoreFileChosen(Uri uri) {
        if (uri == null) return;
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_backup_restore_confirm_title)
                .setMessage(R.string.settings_backup_restore_confirm_message)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(R.string.settings_backup_restore_button, (dialog, which) -> doRestore(uri))
                .show();
    }

    private void doRestore(Uri uri) {
        setBusy(true, "");
        ApplianceHttpClient.restoreUpload(uri, getContentResolver(), new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(org.json.JSONObject body) {
                boolean success = body.optBoolean("success", false);
                String message = body.optString("message", "");
                setBusy(false, success ? message : getString(R.string.settings_backup_restore_failed) + ": " + message);
            }

            @Override
            public void onFailure(String message) {
                setBusy(false, getString(R.string.settings_backup_restore_failed) + ": " + message);
            }
        });
    }

    private void setBusy(boolean busy, String message) {
        progressBar.setVisibility(busy ? View.VISIBLE : View.GONE);
        messageView.setText(message);
        if (!busy && !message.isEmpty()) {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        }
    }

    private static void closeQuietly(OutputStream out) {
        try {
            out.close();
        } catch (Exception ignored) {
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
        context.startActivity(new Intent(context, BackupRestoreActivity.class));
    }
}
