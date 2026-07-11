package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
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
 * OTA channel (stable/dev) + check/apply for each of the appliance's 4
 * update kinds (UI, System, OS, Lyrion Music Server) — mirrors the Electron
 * UI's "Updates" section, simplified (no live progress bar polling; a
 * "Applying…" state plus a final success/failure message is enough for a
 * phone screen the user isn't expected to watch continuously).
 */
public class UpdatesActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private RadioGroup channelGroup;
    private ProgressBar progressBar;
    private boolean suppressChannelEvent;

    private static final class UpdateKind {
        final String pathSegment;
        final int labelRes;

        UpdateKind(String pathSegment, int labelRes) {
            this.pathSegment = pathSegment;
            this.labelRes = labelRes;
        }
    }

    private static final UpdateKind[] KINDS = {
            new UpdateKind("app", R.string.settings_updates_ui),
            new UpdateKind("system", R.string.settings_updates_system),
            new UpdateKind("os", R.string.settings_updates_os),
            new UpdateKind("lyrion", R.string.settings_updates_lyrion),
    };

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
        progressBar = findViewById(R.id.updates_progress);

        channelGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressChannelEvent) return;
            String channel = checkedId == R.id.channel_dev ? "dev" : "prod";
            setChannel(channel);
        });

        LinearLayout list = findViewById(R.id.updates_list);
        for (UpdateKind kind : KINDS) {
            list.addView(buildRow(kind));
        }

        loadChannel();
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

    private View buildRow(UpdateKind kind) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams rowParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rowParams.bottomMargin = dp(20);
        row.setLayoutParams(rowParams);

        TextView title = new TextView(this);
        title.setText(kind.labelRes);
        title.setTextColor(getColor(android.R.color.white));
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        row.addView(title);

        TextView status = new TextView(this);
        status.setText(R.string.settings_updates_up_to_date);
        status.setTextColor(getColor(R.color.hifiSilver));
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        statusParams.bottomMargin = dp(6);
        status.setLayoutParams(statusParams);
        row.addView(status);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        row.addView(buttons);

        MaterialButton checkButton = new MaterialButton(
                new android.view.ContextThemeWrapper(this, com.google.android.material.R.style.Widget_MaterialComponents_Button_OutlinedButton));
        checkButton.setText(R.string.settings_updates_check_button);
        buttons.addView(checkButton);

        MaterialButton applyButton = new MaterialButton(this);
        applyButton.setText(R.string.settings_updates_apply_button);
        applyButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams applyParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        applyParams.leftMargin = dp(8);
        applyButton.setLayoutParams(applyParams);
        buttons.addView(applyButton);

        checkButton.setOnClickListener(v -> check(kind, status, applyButton));
        applyButton.setOnClickListener(v -> apply(kind, status, applyButton));

        return row;
    }

    private void check(UpdateKind kind, TextView status, MaterialButton applyButton) {
        setBusy(true);
        ApplianceHttpClient.getJson("/api/system/updates/" + kind.pathSegment + "/check", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                boolean available = body.optBoolean("update_available", false);
                if (available) {
                    status.setText(getString(R.string.settings_updates_available, body.optString("latest", "?")));
                    applyButton.setVisibility(View.VISIBLE);
                } else {
                    status.setText(R.string.settings_updates_up_to_date);
                    applyButton.setVisibility(View.GONE);
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                status.setText(message);
            }
        });
    }

    private void apply(UpdateKind kind, TextView status, MaterialButton applyButton) {
        setBusy(true);
        status.setText(R.string.settings_updates_applying);
        ApplianceHttpClient.postJson("/api/system/updates/" + kind.pathSegment + "/apply", null, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                status.setText(body.optString("message", getString(R.string.settings_updates_up_to_date)));
                applyButton.setVisibility(View.GONE);
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                status.setText(message);
            }
        });
    }

    private void setBusy(boolean busy) {
        progressBar.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
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
