package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.RadioGroup;
import android.widget.TextView;

import androidx.annotation.StringRes;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONArray;

/**
 * The web admin's Settings → Display card (admin-webui Settings.vue): headless
 * or on-screen, which interface runs on the screen, its render resolution and
 * refresh rate, the mouse pointer, and whether this device plays audio at all.
 * Every change asks first where the web admin does. There is no kiosk-style
 * keep-or-revert countdown: this phone is not the screen being changed.
 */
public class DisplayActivity extends ApplianceSettingsActivity {
    private TextView modeCurrent;
    private MaterialButton modeButton;
    private View screenBlock;
    private View engineBlock;
    private RadioGroup engineGroup;
    private View resolutionBlock;
    private RadioGroup resolutionGroup;
    private View refreshBlock;
    private RadioGroup refreshGroup;
    private TextView refreshUnsupported;
    private View pointerBlock;
    private RadioGroup pointerGroup;
    private TextView pointerUnavailable;
    private View playerBlock;
    private RadioGroup playerGroup;

    private String mode = "";
    private String engine = "";
    private String resolution = "";
    private String refresh = "";
    private boolean pointerEnabled = true;
    private boolean playerEnabled = true;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.appliance_section_display, R.layout.appliance_display);

        modeCurrent = findViewById(R.id.display_mode_current);
        modeButton = findViewById(R.id.button_display_mode);
        screenBlock = findViewById(R.id.display_screen_block);
        engineBlock = findViewById(R.id.display_engine_block);
        engineGroup = findViewById(R.id.display_engine_group);
        resolutionBlock = findViewById(R.id.display_resolution_block);
        resolutionGroup = findViewById(R.id.display_resolution_group);
        refreshBlock = findViewById(R.id.display_refresh_block);
        refreshGroup = findViewById(R.id.display_refresh_group);
        refreshUnsupported = findViewById(R.id.display_refresh_unsupported);
        pointerBlock = findViewById(R.id.display_pointer_block);
        pointerGroup = findViewById(R.id.display_pointer_group);
        pointerUnavailable = findViewById(R.id.display_pointer_unavailable);
        playerBlock = findViewById(R.id.display_player_block);
        playerGroup = findViewById(R.id.display_player_group);

        modeButton.setOnClickListener(v -> {
            if ("headless".equals(mode)) {
                setMode("gui");
            } else {
                confirm(R.string.appliance_display_confirm_headless, () -> setMode("headless"), null);
            }
        });

        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_auto), "auto");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_720), "720");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_1080), "1080");
        addRadio(resolutionGroup, getString(R.string.appliance_display_resolution_native), "native");
        resolutionGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            String m = (String) checkedTag(group, id);
            if (m == null || m.equals(resolution)) return;
            confirm(R.string.appliance_display_confirm_resolution, () -> setResolution(m),
                    () -> checkByTag(resolutionGroup, resolution));
        });

        addRadio(refreshGroup, getString(R.string.settings_ui_refresh_native), "native");
        addRadio(refreshGroup, getString(R.string.settings_ui_refresh_low), "low");
        refreshGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            String m = (String) checkedTag(group, id);
            if (m == null || m.equals(refresh)) return;
            if ("low".equals(m)) {
                confirm(R.string.settings_ui_refresh_confirm, () -> setRefresh(m), () -> checkByTag(refreshGroup, refresh));
            } else {
                setRefresh(m);
            }
        });

        addRadio(pointerGroup, getString(R.string.appliance_display_pointer_on), true);
        addRadio(pointerGroup, getString(R.string.appliance_display_pointer_off), false);
        pointerGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Boolean on = (Boolean) checkedTag(group, id);
            if (on != null && on != pointerEnabled) setPointer(on);
        });

        addRadio(playerGroup, getString(R.string.appliance_display_player_on), true);
        addRadio(playerGroup, getString(R.string.appliance_display_player_off), false);
        playerGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Boolean on = (Boolean) checkedTag(group, id);
            if (on == null || on == playerEnabled) return;
            if (on) {
                setPlayer(true);
            } else {
                confirm(R.string.appliance_display_confirm_player_off, () -> setPlayer(false),
                        () -> checkByTag(playerGroup, playerEnabled));
            }
        });

        loadMode();
        loadEngine();
        loadResolution();
        loadRefresh();
        loadPointer();
        loadPlayer();
    }

    private void confirm(@StringRes int message, Runnable onYes, Runnable onNo) {
        new MaterialAlertDialogBuilder(this)
                .setMessage(message)
                .setNegativeButton(android.R.string.cancel, (d, w) -> { if (onNo != null) onNo.run(); })
                .setOnCancelListener(d -> { if (onNo != null) onNo.run(); })
                .setPositiveButton(android.R.string.ok, (d, w) -> onYes.run())
                .show();
    }

    // ── headless / on-screen ────────────────────────────────────────────
    private void renderMode() {
        boolean headless = "headless".equals(mode);
        modeCurrent.setText(getString(R.string.appliance_display_current,
                getString(headless ? R.string.appliance_display_headless : R.string.appliance_display_onscreen)));
        modeButton.setText(headless ? R.string.appliance_display_switch_to_onscreen : R.string.appliance_display_switch_to_headless);
        modeButton.setVisibility(View.VISIBLE);
        screenBlock.setVisibility(headless ? View.GONE : View.VISIBLE);
    }

    private void loadMode() {
        load("/api/system/display_mode", "mode", body -> {
            mode = body.optString("mode", "gui");
            renderMode();
        }, null);
    }

    private void setMode(String m) {
        post("/api/system/display_mode", json("mode", m), R.string.appliance_display_change_failed, body -> {
            mode = body.optString("mode", m);
            renderMode();
            showMessage(messageOf(body, getString(R.string.appliance_display_changed)));
        }, null);
    }

    // ── which interface runs on the screen ──────────────────────────────
    // The appliance only lists "qt" once its files are really installed, so a
    // unit that hasn't received that package never offers a switch that would
    // leave it with a black screen.
    private void loadEngine() {
        load("/api/system/ui_engine", "engine", body -> {
            engine = body.optString("engine", "");
            JSONArray list = body.optJSONArray("engines");
            engineGroup.removeAllViews();
            if (list == null || list.length() < 2) {
                engineBlock.setVisibility(View.GONE);
                return;
            }
            for (int i = 0; i < list.length(); i++) {
                String e = list.optString(i);
                addRadio(engineGroup, engineLabel(e), e);
            }
            checkByTag(engineGroup, engine);
            engineGroup.setOnCheckedChangeListener((group, id) -> {
                if (isQuiet()) return;
                String e = (String) checkedTag(group, id);
                if (e == null || e.equals(engine)) return;
                confirm(R.string.appliance_display_confirm_engine, () -> setEngine(e), () -> checkByTag(engineGroup, engine));
            });
            engineBlock.setVisibility(View.VISIBLE);
        }, () -> engineBlock.setVisibility(View.GONE));
    }

    private String engineLabel(String e) {
        if ("electron".equals(e)) return getString(R.string.appliance_display_engine_electron);
        if ("qt".equals(e)) return getString(R.string.appliance_display_engine_qt);
        return e;
    }

    private void setEngine(String e) {
        post("/api/system/ui_engine", json("engine", e), R.string.appliance_display_engine_failed, body -> {
            engine = body.optString("engine", e);
            checkByTag(engineGroup, engine);
            showMessage(messageOf(body, getString(R.string.appliance_display_engine_changed)));
        }, () -> checkByTag(engineGroup, engine));
    }

    // ── render resolution ───────────────────────────────────────────────
    private void loadResolution() {
        load("/api/system/ui_resolution", "mode", body -> {
            resolution = body.optString("mode", "auto");
            checkByTag(resolutionGroup, resolution);
            resolutionBlock.setVisibility(View.VISIBLE);
        }, () -> resolutionBlock.setVisibility(View.GONE));
    }

    private void setResolution(String m) {
        post("/api/system/ui_resolution", json("mode", m), R.string.settings_ui_resolution_failed, body -> {
            resolution = body.optString("mode", m);
            checkByTag(resolutionGroup, resolution);
            showMessage(messageOf(body, getString(R.string.settings_ui_resolution_changed)));
        }, () -> checkByTag(resolutionGroup, resolution));
    }

    // ── refresh rate ────────────────────────────────────────────────────
    private void loadRefresh() {
        load("/api/system/ui_refresh", "mode", body -> {
            refresh = body.optString("mode", "native");
            // Per unit: not every panel offers a lower mode at its native
            // resolution. Say so instead of a choice that would do nothing.
            boolean supported = body.optBoolean("supported", true);
            refreshGroup.setVisibility(supported ? View.VISIBLE : View.GONE);
            refreshUnsupported.setVisibility(supported ? View.GONE : View.VISIBLE);
            checkByTag(refreshGroup, refresh);
            refreshBlock.setVisibility(View.VISIBLE);
        }, () -> refreshBlock.setVisibility(View.GONE));
    }

    private void setRefresh(String m) {
        post("/api/system/ui_refresh", json("mode", m), R.string.settings_ui_refresh_failed, body -> {
            refresh = body.optString("mode", m);
            checkByTag(refreshGroup, refresh);
            showMessage(messageOf(body, getString(R.string.settings_ui_refresh_changed)));
        }, () -> {
            // The appliance reports the mode still in force with a refusal.
            checkByTag(refreshGroup, refresh);
            loadRefresh();
        });
    }

    // ── mouse pointer ───────────────────────────────────────────────────
    private void loadPointer() {
        load("/api/system/pointer_status", "enabled", body -> {
            pointerEnabled = body.optBoolean("enabled", true);
            pointerUnavailable.setVisibility(body.optBoolean("available", true) ? View.GONE : View.VISIBLE);
            checkByTag(pointerGroup, pointerEnabled);
            pointerBlock.setVisibility(View.VISIBLE);
        }, () -> pointerBlock.setVisibility(View.GONE));
    }

    private void setPointer(boolean on) {
        post("/api/system/pointer_set", json("enable", on), R.string.appliance_display_pointer_failed, body -> {
            pointerEnabled = body.optBoolean("enabled", on);
            checkByTag(pointerGroup, pointerEnabled);
            showMessage(messageOf(body, getString(R.string.appliance_display_pointer_changed)));
        }, () -> checkByTag(pointerGroup, pointerEnabled));
    }

    // ── player on/off (server-only unit) ────────────────────────────────
    private void loadPlayer() {
        load("/api/system/player_enabled", "enabled", body -> {
            playerEnabled = body.optBoolean("enabled", true);
            checkByTag(playerGroup, playerEnabled);
            playerBlock.setVisibility(View.VISIBLE);
        }, () -> playerBlock.setVisibility(View.GONE));
    }

    private void setPlayer(boolean on) {
        post("/api/system/player_enabled", json("enabled", on), R.string.appliance_display_player_failed, body -> {
            playerEnabled = body.optBoolean("enabled", on);
            checkByTag(playerGroup, playerEnabled);
            showMessage(messageOf(body, getString(R.string.appliance_display_player_changed)));
        }, () -> checkByTag(playerGroup, playerEnabled));
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, DisplayActivity.class));
    }
}
