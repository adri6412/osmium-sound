package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MenuItem;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;
import com.google.android.material.textfield.TextInputEditText;

import org.json.JSONArray;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * DSP enable/disable, room-correction and crossfeed toggles, balance,
 * named presets, and convolution filter (WAV/TXT impulse response)
 * upload/status/removal — talks to the appliance via ApplianceHttpClient
 * (sources_server.py's /api/dsp/* routes).
 * Full parametric EQ band editing is intentionally out of scope here (the
 * appliance's local kiosk UI already has that); this screen exposes
 * toggles, balance, presets, and filter upload/manage.
 */
public class DspSettingsActivity extends AppCompatActivity {
    private static final double BALANCE_MAX = 12.0;
    private static final int BALANCE_STEPS = 48; // 0.5 dB per SeekBar step, -12..+12

    // Biquad types set_dsp accepts, in the order shown by each band's type
    // spinner. Highpass/Lowpass take no gain (the backend rejects one).
    private static final String[] BAND_TYPES = {"Peaking", "Lowshelf", "Highshelf", "Highpass", "Lowpass"};
    private static final int BAND_TYPE_HIGHPASS = 3;
    private static final int BAND_TYPE_LOWPASS = 4;

    private final ThemeManager mThemeManager = new ThemeManager();

    private View unavailableMessage;
    private View rowEnabled, rowRoomCorrection, rowCrossfeed, rowBalance;
    private SwitchMaterial switchEnabled, switchRoomCorrection, switchCrossfeed;
    private SeekBar balanceSeekBar;
    private TextView balanceValue;
    private ChipGroup presetsChipGroup;
    private TextInputEditText presetNameInput;
    private View buttonSavePreset;
    private View eqSection;
    private TextView eqNoBands;
    private LinearLayout eqBandsContainer;
    private TextView filterStatus;
    private View buttonUpload, buttonRemove;
    private ProgressBar progressBar;
    private TextView messageView;

    private boolean crossfeed;
    private boolean roomCorrection;
    private double balance;
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
        rowBalance = findViewById(R.id.dsp_row_balance);
        switchEnabled = findViewById(R.id.switch_dsp_enabled);
        switchRoomCorrection = findViewById(R.id.switch_room_correction);
        switchCrossfeed = findViewById(R.id.switch_crossfeed);
        balanceSeekBar = findViewById(R.id.dsp_balance_seekbar);
        balanceValue = findViewById(R.id.dsp_balance_value);
        presetsChipGroup = findViewById(R.id.dsp_presets_chip_group);
        presetNameInput = findViewById(R.id.dsp_preset_name_input);
        buttonSavePreset = findViewById(R.id.button_save_preset);
        eqSection = findViewById(R.id.dsp_eq_section);
        eqNoBands = findViewById(R.id.dsp_eq_no_bands);
        eqBandsContainer = findViewById(R.id.dsp_eq_bands_container);
        filterStatus = findViewById(R.id.dsp_filter_status);
        buttonUpload = findViewById(R.id.button_upload_filter);
        buttonRemove = findViewById(R.id.button_remove_filter);
        progressBar = findViewById(R.id.dsp_progress);
        messageView = findViewById(R.id.dsp_message);

        pickFilterLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onFilterChosen);

        switchEnabled.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) applyDspPatch(singleKeyPatch("enabled", checked)); });
        switchRoomCorrection.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) { roomCorrection = checked; applyDspPatch(singleKeyPatch("room_correction", checked)); } });
        switchCrossfeed.setOnCheckedChangeListener((btn, checked) -> { if (!suppressToggleEvents) { crossfeed = checked; applyDspPatch(singleKeyPatch("crossfeed", checked)); } });

        balanceSeekBar.setMax(BALANCE_STEPS);
        balanceSeekBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                balance = progress / 2.0 - BALANCE_MAX;
                updateBalanceLabel();
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) { }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                if (!suppressToggleEvents) {
                    JSONObject patch = new JSONObject();
                    try {
                        patch.put("balance", balance);
                    } catch (Exception ignored) {
                    }
                    applyDspPatch(patch);
                }
            }
        });

        buttonSavePreset.setOnClickListener(v -> saveCurrentAsPreset());

        findViewById(R.id.button_add_band).setOnClickListener(v -> {
            JSONObject band = new JSONObject();
            try {
                band.put("type", "Peaking");
                band.put("freq", 1000);
                band.put("gain", 0);
                band.put("q", 1.0);
            } catch (Exception ignored) {
            }
            eqBandsContainer.addView(buildBandRow(band));
            updateEqEmptyVisibility();
        });
        findViewById(R.id.button_apply_eq).setOnClickListener(v -> {
            JSONObject patch = new JSONObject();
            try {
                patch.put("bands", harvestBands());
            } catch (Exception ignored) {
            }
            // A bands edit clears the active preset server-side — refresh the
            // chip row afterwards so the UI reflects that.
            applyDspPatch(patch, this::loadPresets);
        });

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
                loadPresets();
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
        rowBalance.setVisibility(rowVisibility);
        balanceSeekBar.setVisibility(rowVisibility);
        buttonUpload.setVisibility(rowVisibility);
        buttonRemove.setVisibility(rowVisibility);
        eqSection.setVisibility(rowVisibility);
        if (!available) return;

        roomCorrection = status.optBoolean("room_correction", false);
        crossfeed = status.optBoolean("crossfeed", false);
        balance = status.optDouble("balance", 0.0);
        if (Double.isNaN(balance)) balance = 0.0;

        renderEqBands(status.optJSONArray("bands"));

        suppressToggleEvents = true;
        switchEnabled.setChecked(status.optBoolean("enabled", false));
        switchRoomCorrection.setChecked(roomCorrection);
        switchCrossfeed.setChecked(crossfeed);
        balanceSeekBar.setProgress((int) Math.round((balance + BALANCE_MAX) * 2));
        updateBalanceLabel();
        suppressToggleEvents = false;
    }

    private void updateBalanceLabel() {
        if (Math.abs(balance) < 0.05) {
            balanceValue.setText(R.string.settings_dsp_balance_center);
        } else if (balance < 0) {
            balanceValue.setText(getString(R.string.settings_dsp_balance_left, Math.abs(balance)));
        } else {
            balanceValue.setText(getString(R.string.settings_dsp_balance_right, balance));
        }
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

    private JSONObject singleKeyPatch(String key, boolean value) {
        JSONObject patch = new JSONObject();
        try {
            patch.put(key, value);
        } catch (Exception ignored) {
        }
        return patch;
    }

    // Sends ONLY the key(s) the user just changed. The appliance's set_dsp()
    // applies merge semantics — any key omitted keeps its last stored value —
    // so this screen (which doesn't edit EQ bands) can never wipe the
    // parametric EQ configured from the appliance's own touchscreen Settings.
    // Single-key patches also matter for the active-preset name: the backend
    // clears it whenever a tone key (crossfeed/balance/…) appears in the
    // payload, so bundling the full state with every change (as this screen
    // used to) made a plain DSP on/off toggle silently deselect the active
    // preset chip.
    private void applyDspPatch(JSONObject config) {
        applyDspPatch(config, null);
    }

    private void applyDspPatch(JSONObject config, @androidx.annotation.Nullable Runnable onSuccess) {
        setBusy(true);
        ApplianceHttpClient.dspSet(config, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (!body.optBoolean("success", true)) {
                    showMessage(body.optString("message", getString(R.string.settings_dsp_status_failed)));
                } else if (onSuccess != null) {
                    onSuccess.run();
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_status_failed) + ": " + message);
            }
        });
    }

    // ── Parametric EQ bands ──────────────────────────────────────────
    // Rows are plain programmatic views (≤20 bands, no recycler needed);
    // values live in the row widgets themselves and are harvested into JSON
    // on Apply — the backend's _clean_bands() clamps/validates server-side.

    /** Per-row widget references, stashed in the row view's tag. */
    private static class BandRowHolder {
        final Spinner type;
        final EditText freq, gain, q;
        BandRowHolder(Spinner type, EditText freq, EditText gain, EditText q) {
            this.type = type; this.freq = freq; this.gain = gain; this.q = q;
        }
    }

    private void renderEqBands(JSONArray bands) {
        eqBandsContainer.removeAllViews();
        if (bands != null) {
            for (int i = 0; i < bands.length(); i++) {
                JSONObject band = bands.optJSONObject(i);
                if (band != null) eqBandsContainer.addView(buildBandRow(band));
            }
        }
        updateEqEmptyVisibility();
    }

    private void updateEqEmptyVisibility() {
        eqNoBands.setVisibility(eqBandsContainer.getChildCount() == 0 ? View.VISIBLE : View.GONE);
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value,
                getResources().getDisplayMetrics());
    }

    private EditText makeNumberField(String initial, String hint, boolean signed) {
        EditText field = new EditText(this);
        field.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL
                | (signed ? InputType.TYPE_NUMBER_FLAG_SIGNED : 0));
        field.setHint(hint);
        field.setText(initial);
        field.setMaxLines(1);
        return field;
    }

    /** Render a number dropping a trailing ".0" (freq 1000.0 → "1000"). */
    private static String formatNumber(double v) {
        return v == Math.rint(v) ? String.valueOf((long) v) : String.valueOf(v);
    }

    private View buildBandRow(JSONObject band) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        rowLp.bottomMargin = dp(4);
        row.setLayoutParams(rowLp);

        Spinner type = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, new String[]{
                getString(R.string.settings_dsp_band_type_peaking),
                getString(R.string.settings_dsp_band_type_lowshelf),
                getString(R.string.settings_dsp_band_type_highshelf),
                getString(R.string.settings_dsp_band_type_highpass),
                getString(R.string.settings_dsp_band_type_lowpass)});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        type.setAdapter(adapter);
        String bandType = band.optString("type", "Peaking");
        for (int i = 0; i < BAND_TYPES.length; i++) {
            if (BAND_TYPES[i].equals(bandType)) {
                type.setSelection(i);
                break;
            }
        }

        EditText freq = makeNumberField(formatNumber(band.optDouble("freq", 1000)),
                getString(R.string.settings_dsp_eq_freq_hint), false);
        EditText gain = makeNumberField(formatNumber(band.optDouble("gain", 0)),
                getString(R.string.settings_dsp_eq_gain_hint), true);
        EditText q = makeNumberField(formatNumber(band.optDouble("q", 1.0)),
                getString(R.string.settings_dsp_eq_q_hint), false);

        type.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                boolean hasGain = position != BAND_TYPE_HIGHPASS && position != BAND_TYPE_LOWPASS;
                gain.setEnabled(hasGain);
                gain.setAlpha(hasGain ? 1f : 0.4f);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) { }
        });

        com.google.android.material.button.MaterialButton remove =
                new com.google.android.material.button.MaterialButton(this, null,
                        com.google.android.material.R.attr.materialButtonOutlinedStyle);
        remove.setText("✕");
        remove.setMinWidth(dp(40));
        remove.setMinimumWidth(dp(40));
        remove.setOnClickListener(v -> {
            eqBandsContainer.removeView(row);
            updateEqEmptyVisibility();
        });

        row.addView(type, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.4f));
        row.addView(freq, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        row.addView(gain, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 0.8f));
        row.addView(q, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 0.8f));
        row.addView(remove, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        row.setTag(new BandRowHolder(type, freq, gain, q));
        return row;
    }

    private static double parseOr(EditText field, double fallback) {
        try {
            return Double.parseDouble(field.getText().toString().trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private JSONArray harvestBands() {
        JSONArray bands = new JSONArray();
        for (int i = 0; i < eqBandsContainer.getChildCount(); i++) {
            Object tag = eqBandsContainer.getChildAt(i).getTag();
            if (!(tag instanceof BandRowHolder)) continue;
            BandRowHolder holder = (BandRowHolder) tag;
            int typeIdx = holder.type.getSelectedItemPosition();
            if (typeIdx < 0 || typeIdx >= BAND_TYPES.length) typeIdx = 0;
            try {
                JSONObject band = new JSONObject();
                band.put("type", BAND_TYPES[typeIdx]);
                band.put("freq", parseOr(holder.freq, 1000));
                if (typeIdx != BAND_TYPE_HIGHPASS && typeIdx != BAND_TYPE_LOWPASS) {
                    band.put("gain", parseOr(holder.gain, 0));
                }
                band.put("q", parseOr(holder.q, 1.0));
                bands.put(band);
            } catch (Exception ignored) {
            }
        }
        return bands;
    }

    // ── Presets ──────────────────────────────────────────────────────

    private void loadPresets() {
        ApplianceHttpClient.dspPresets(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                renderPresets(body.optJSONArray("presets"), body.optString("active", null));
            }

            @Override
            public void onFailure(String message) {
                // Older appliance System bundle without the presets endpoint —
                // degrade gracefully by hiding the row instead of erroring.
                presetsChipGroup.setVisibility(View.GONE);
            }
        });
    }

    private void renderPresets(JSONArray presets, String activeName) {
        presetsChipGroup.removeAllViews();
        if (presets == null) {
            presetsChipGroup.setVisibility(View.GONE);
            return;
        }
        presetsChipGroup.setVisibility(View.VISIBLE);

        Chip customChip = new Chip(this);
        customChip.setText(R.string.settings_dsp_preset_custom);
        customChip.setCheckable(true);
        customChip.setChecked(activeName == null);
        customChip.setClickable(false);
        presetsChipGroup.addView(customChip);

        for (int i = 0; i < presets.length(); i++) {
            JSONObject p = presets.optJSONObject(i);
            if (p == null) continue;
            String name = p.optString("name", "");
            boolean builtin = p.optBoolean("builtin", false);
            Chip chip = new Chip(this);
            chip.setText(builtin ? builtinPresetLabel(name) : name);
            chip.setCheckable(true);
            chip.setChecked(name.equals(activeName));
            chip.setCloseIconVisible(!builtin);
            if (!builtin) {
                chip.setOnCloseIconClickListener(v -> confirmDeletePreset(name));
            }
            chip.setOnClickListener(v -> applyPreset(name));
            presetsChipGroup.addView(chip);
        }
    }

    private String builtinPresetLabel(String name) {
        if ("Flat".equals(name)) return getString(R.string.settings_dsp_preset_flat);
        if ("Warm".equals(name)) return getString(R.string.settings_dsp_preset_warm);
        if ("Bright".equals(name)) return getString(R.string.settings_dsp_preset_bright);
        if ("Loudness (low volume)".equals(name)) return getString(R.string.settings_dsp_preset_loudness);
        return name;
    }

    private void applyPreset(String name) {
        setBusy(true);
        ApplianceHttpClient.dspPresetLoad(name, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (body.optBoolean("success", false)) {
                    showMessage(getString(R.string.settings_dsp_preset_loaded));
                    loadStatus(); // re-sync toggles/balance/preset chips from the new state
                } else {
                    setBusy(false);
                    showMessage(body.optString("message", getString(R.string.settings_dsp_preset_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_preset_failed) + ": " + message);
            }
        });
    }

    private void saveCurrentAsPreset() {
        String name = presetNameInput.getText() != null ? presetNameInput.getText().toString().trim() : "";
        if (name.isEmpty()) return;
        setBusy(true);
        ApplianceHttpClient.dspPresetSave(name, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", false)) {
                    presetNameInput.setText("");
                    showMessage(getString(R.string.settings_dsp_preset_saved));
                    renderPresets(body.optJSONArray("presets"), body.optString("active", name));
                } else {
                    showMessage(body.optString("message", getString(R.string.settings_dsp_preset_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_preset_failed) + ": " + message);
            }
        });
    }

    private void confirmDeletePreset(String name) {
        new MaterialAlertDialogBuilder(this)
                .setMessage(getString(R.string.settings_dsp_preset_delete_confirm, name))
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> deletePreset(name))
                .show();
    }

    private void deletePreset(String name) {
        setBusy(true);
        ApplianceHttpClient.dspPresetDelete(name, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                setBusy(false);
                if (body.optBoolean("success", false)) {
                    renderPresets(body.optJSONArray("presets"), body.optString("active", null));
                } else {
                    showMessage(body.optString("message", getString(R.string.settings_dsp_preset_failed)));
                }
            }

            @Override
            public void onFailure(String message) {
                setBusy(false);
                showMessage(getString(R.string.settings_dsp_preset_failed) + ": " + message);
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
