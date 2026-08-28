/*
 * Copyright (c) 2012 Google Inc.  All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.osmium.sound.companion.dialog;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.text.Editable;
import android.util.AttributeSet;
import android.view.View;
import android.widget.AutoCompleteTextView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.textfield.TextInputLayout;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;

import java.net.URI;

import com.osmium.sound.companion.Preferences;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.Util;
import com.osmium.sound.companion.util.AfterTextChangedLister;

/**
 * Walks the user through setting up a connection.
 * <p>
 * The first step asks what they are connecting to, because the two answers want
 * different things:
 * <ul>
 *   <li>an <b>Osmium Sound</b> appliance is paired by scanning its "Phone
 *       control" QR code, and only that way: typing a host by hand would connect
 *       the app without the pairing token that gates the appliance's own API
 *       (see sources_server.py's /api/pair/token and
 *       {@link Preferences#setAppliancePairing}), leaving the appliance settings
 *       visible but dead. Steps then run scan, confirm, ready;</li>
 *   <li>any <b>other Lyrion server</b> has no QR code and no appliance API, so
 *       the address is typed in and the appliance settings stay hidden. Steps
 *       run mode, ready.</li>
 * </ul>
 */
public class ServerAddressView extends LinearLayout {

    /** The screens of the wizard, shown one at a time. */
    public enum Step { MODE, SCAN, CONFIRM, READY }

    /** Notified whenever the wizard advances/returns to a different step. */
    public interface StepListener {
        void onStepChanged(Step step);
    }

    private Preferences preferences;
    private Preferences.ServerAddress serverAddress;

    private TextView stepIndicator;
    private View modeGroup;
    private MaterialButton modeOsmiumButton;
    private MaterialButton modeStandardButton;
    private View scanGroup;
    private MaterialButton scanButton;
    private MaterialCardView confirmGroup;
    private TextView confirmMessage;
    private MaterialButton confirmPairButton;
    private MaterialButton confirmRescanButton;
    private View readyGroup;
    private MaterialButton advancedOptionsToggle;
    private View advancedOptionsGroup;

    private AutoCompleteTextView serverAddressEditText;
    private EditText userNameEditText;
    private EditText passwordEditText;
    private MaterialCheckBox wakeOnLan;
    private TextInputLayout macLayout;
    private boolean macDirty;
    private EditText macEditText;

    private Step currentStep;
    private Preferences.ServerKind serverKind;
    private StepListener stepListener;
    private String pendingHostPort;
    private String pendingApi;
    private String pendingToken;

    public ServerAddressView(final Context context) {
        super(context);
        initialize();
    }

    public ServerAddressView(Context context, AttributeSet attrs) {
        super(context, attrs);
        initialize();
    }

    private void initialize() {
        inflate(getContext(), R.layout.server_address_view, this);
        if (!isInEditMode()) {
            stepIndicator = findViewById(R.id.wizard_step_indicator);
            modeGroup = findViewById(R.id.step_mode);
            modeOsmiumButton = findViewById(R.id.mode_osmium_button);
            modeOsmiumButton.setOnClickListener(view -> chooseServerKind(Preferences.ServerKind.OSMIUM));
            modeStandardButton = findViewById(R.id.mode_standard_button);
            modeStandardButton.setOnClickListener(view -> chooseServerKind(Preferences.ServerKind.STANDARD_LMS));
            scanGroup = findViewById(R.id.step_scan);
            scanButton = findViewById(R.id.scan_button);
            scanButton.setOnClickListener(view -> startQrScan());
            confirmGroup = findViewById(R.id.step_confirm);
            confirmMessage = findViewById(R.id.confirm_message);
            confirmPairButton = findViewById(R.id.confirm_pair_button);
            confirmPairButton.setOnClickListener(view -> confirmPendingPairing());
            confirmRescanButton = findViewById(R.id.confirm_rescan_button);
            confirmRescanButton.setOnClickListener(view -> startQrScan());
            readyGroup = findViewById(R.id.step_ready);
            // Lets the choice be revisited without reinstalling; the address and
            // any pairing stay put until a different kind is actually picked.
            findViewById(R.id.change_mode_button).setOnClickListener(view -> setStep(Step.MODE));
            advancedOptionsToggle = findViewById(R.id.advanced_options_toggle);
            advancedOptionsGroup = findViewById(R.id.advanced_options_group);
            advancedOptionsToggle.setOnClickListener(view -> setAdvancedOptionsExpanded(
                    advancedOptionsGroup.getVisibility() != VISIBLE));

            HiFiMediaPlayer.getPreferences(prefs -> {
                preferences = prefs;
                serverAddress = preferences.getServerAddress();
                if (serverAddress.localAddress() == null) {
                    Preferences.ServerAddress cliServerAddress = preferences.getCliServerAddress();
                    if (cliServerAddress.localAddress() != null) {
                        serverAddress.setAddress(cliServerAddress.localHost());
                    }
                }

                serverAddressEditText = findViewById(R.id.server_address);
                // Read-only: the only way to (re)set the server address is scanning the
                // appliance's pairing QR (see class doc). Tapping the field itself
                // also starts a scan, same as the end icon.
                serverAddressEditText.setFocusable(false);
                serverAddressEditText.setLongClickable(false);
                serverAddressEditText.setOnClickListener(view -> startQrScan());
                TextInputLayout serverAddressTil = findViewById(R.id.server_address_til);
                serverAddressTil.setEndIconOnClickListener(view -> startQrScan());
                userNameEditText = findViewById(R.id.username);
                passwordEditText = findViewById(R.id.password);

                wakeOnLan = findViewById(R.id.wol);
                wakeOnLan.setOnCheckedChangeListener((compoundButton, b) -> macLayout.setVisibility(b ? VISIBLE : GONE));
                macLayout = findViewById(R.id.mac_til);
                macEditText = findViewById(R.id.mac);
                macLayout.setEndIconOnClickListener(view -> {
                    FragmentManager fragmentManager = ((AppCompatActivity) getContext()).getSupportFragmentManager();
                    InfoDialog.show(fragmentManager, R.string.settings_MAC_label, R.string.settings_MAC_info);
                });
                macLayout.setErrorIconOnClickListener(view -> {
                    FragmentManager fragmentManager = ((AppCompatActivity) getContext()).getSupportFragmentManager();
                    InfoDialog.show(fragmentManager, R.string.settings_MAC_label, R.string.settings_MAC_info);
                });
                macEditText.setOnFocusChangeListener((view, b) -> {
                    if (!b) {
                        checkMac();
                    }
                });
                macEditText.addTextChangedListener(new AfterTextChangedLister() {
                    @Override
                    public void afterTextChanged(Editable editable) {
                        if (macDirty) {
                            macLayout.setError(Util.validateMac(editable.toString()) ? null : getResources().getString(R.string.settings_invalid_MAC));
                        }
                    }
                });

                serverKind = preferences.getServerKind();
                setServerAddress(serverAddress.localAddress());
                if (serverKind == null) {
                    // Someone who paired before this choice existed was on an
                    // appliance by definition: keep them there rather than
                    // asking a question they have effectively already answered.
                    if (serverAddress.localAddress() != null) {
                        serverKind = Preferences.ServerKind.OSMIUM;
                        preferences.setServerKind(serverKind);
                    }
                }
                applyServerKind();
                if (serverKind == null) {
                    setStep(Step.MODE);
                } else {
                    setStep(serverAddress.localAddress() != null || isStandardLms()
                            ? Step.READY : Step.SCAN);
                }
            });
        }
    }

    private boolean checkMac() {
        macDirty = true;
        String mac = macEditText.getText().toString();
        boolean macOk = Util.validateMac(mac);
        macLayout.setError(macOk ? null : "Invalid MAC address");
        return macOk;
    }

    public boolean savePreferences() {
        if (wakeOnLan.isChecked() && !checkMac()) {
            return false;
        }

        String address = serverAddressEditText.getText().toString();
        if (isStandardLms() && address.trim().isEmpty()) {
            TextInputLayout serverAddressTil = findViewById(R.id.server_address_til);
            serverAddressTil.setError(getResources().getString(R.string.settings_server_address_required));
            return false;
        }
        serverAddress.setAddress(address);
        serverAddress.userName = userNameEditText.getText().toString();
        serverAddress.password = passwordEditText.getText().toString();
        serverAddress.wakeOnLan = wakeOnLan.isChecked();
        serverAddress.mac = Util.parseMac(macEditText.getText().toString());
        preferences.saveServerAddress(serverAddress);

        return true;
    }

    private boolean isStandardLms() {
        return serverKind == Preferences.ServerKind.STANDARD_LMS;
    }

    /** Records the answer to the first question and moves to the right step. */
    private void chooseServerKind(Preferences.ServerKind kind) {
        serverKind = kind;
        preferences.setServerKind(kind);
        applyServerKind();
        if (kind == Preferences.ServerKind.OSMIUM) {
            setStep(serverAddress.localAddress() != null ? Step.READY : Step.SCAN);
        } else {
            setStep(Step.READY);
        }
    }

    /**
     * The address field is read-only and opens the scanner for an appliance,
     * and an ordinary text field for any other server.
     */
    private void applyServerKind() {
        if (serverAddressEditText == null) return;
        boolean standard = isStandardLms();
        serverAddressEditText.setFocusable(standard);
        serverAddressEditText.setFocusableInTouchMode(standard);
        serverAddressEditText.setLongClickable(standard);
        serverAddressEditText.setOnClickListener(standard ? null : view -> startQrScan());
        TextInputLayout serverAddressTil = findViewById(R.id.server_address_til);
        serverAddressTil.setEndIconMode(standard ? TextInputLayout.END_ICON_NONE
                : TextInputLayout.END_ICON_CUSTOM);
        if (standard) {
            serverAddressTil.setHelperText(getResources().getString(R.string.settings_server_address_required));
        } else {
            serverAddressTil.setHelperText(null);
        }
    }

    /** Registers a listener for step changes, and immediately reports the current step if known. */
    public void setStepListener(StepListener listener) {
        this.stepListener = listener;
        if (listener != null && currentStep != null) {
            listener.onStepChanged(currentStep);
        }
    }

    public Step getStep() {
        return currentStep;
    }

    /** Expands the collapsed username/password/Wake-on-LAN section, e.g. after a login failure. */
    public void expandAdvancedOptions() {
        setAdvancedOptionsExpanded(true);
    }

    private void setAdvancedOptionsExpanded(boolean expanded) {
        advancedOptionsGroup.setVisibility(expanded ? VISIBLE : GONE);
    }

    private void setStep(Step step) {
        currentStep = step;
        modeGroup.setVisibility(step == Step.MODE ? VISIBLE : GONE);
        scanGroup.setVisibility(step == Step.SCAN ? VISIBLE : GONE);
        confirmGroup.setVisibility(step == Step.CONFIRM ? VISIBLE : GONE);
        readyGroup.setVisibility(step == Step.READY ? VISIBLE : GONE);

        int titleRes = switch (step) {
            case MODE -> R.string.wizard_step_title_mode;
            case SCAN -> R.string.wizard_step_title_scan;
            case CONFIRM -> R.string.wizard_step_title_confirm;
            case READY -> R.string.wizard_step_title_ready;
        };
        // A plain Lyrion server skips scanning and confirming, so the count has
        // to follow the path the user is actually on.
        int totalSteps = isStandardLms() ? 2 : Step.values().length;
        int stepNumber = isStandardLms() && step == Step.READY ? 2 : step.ordinal() + 1;
        stepIndicator.setText(getResources().getString(R.string.wizard_step_label, stepNumber, totalSteps,
                getResources().getString(titleRes)));

        if (stepListener != null) {
            stepListener.onStepChanged(step);
        }
    }

    /**
     * Launches the ZXing scanner activity to read the QR code shown on the appliance
     * (Settings -> Phone control). Camera permission is requested by the scanner
     * activity itself if needed. Uses the classic startActivityForResult-based
     * IntentIntegrator (not the newer Activity Result API) because ServerAddressView
     * is a plain View inflated asynchronously ÔÇö it has no safe point to register an
     * ActivityResultLauncher before the host Activity leaves the STARTED state.
     */
    private void startQrScan() {
        if (!(getContext() instanceof Activity)) {
            return;
        }
        IntentIntegrator integrator = new IntentIntegrator((Activity) getContext());
        integrator.setDesiredBarcodeFormats(IntentIntegrator.QR_CODE);
        integrator.setPrompt(getResources().getString(R.string.settings_scan_qr_prompt));
        integrator.setBeepEnabled(false);
        integrator.setOrientationLocked(true);
        integrator.initiateScan();
    }

    /**
     * Forwards the host Activity's onActivityResult here so a completed QR scan can
     * advance the wizard. Returns true if the result was consumed (i.e. it was a scan
     * result at all, scanned or cancelled).
     */
    public boolean handleActivityResult(int requestCode, int resultCode, Intent data) {
        IntentResult result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data);
        if (result == null) {
            return false;
        }
        String contents = result.getContents();
        if (contents == null) {
            return true; // user cancelled the scan, stay on the current step
        }

        String lms = contents;
        String api = null;
        String token = null;
        org.json.JSONObject pairing = parsePairingJson(contents);
        if (pairing != null) {
            lms = pairing.optString("lms", null);
            api = pairing.optString("api", null);
            token = pairing.optString("token", null);
        }

        String hostPort = parseHostPortFromQr(lms);
        if (hostPort == null) {
            Toast.makeText(getContext(), R.string.settings_scan_qr_failed, Toast.LENGTH_LONG).show();
            return true;
        }
        if (api != null && token != null && preferences != null) {
            pendingHostPort = hostPort;
            pendingApi = api;
            pendingToken = token;
            confirmMessage.setText(getResources().getString(R.string.settings_pair_confirm_message, api));
            setStep(Step.CONFIRM);
        } else {
            setServerAddress(hostPort);
            setStep(Step.READY);
        }
        return true;
    }

    /**
     * A scanned pairing QR silently repointing the app's Bearer-token-authenticated
     * control channel (reboot/shutdown/SSH/backup-restore) at a new host is a
     * meaningful trust decision — e.g. a substituted/stickered-over malicious QR
     * code would otherwise be indistinguishable from the real one. Show the
     * resolved host and require explicit confirmation before persisting it,
     * rather than pairing silently the instant a QR is scanned.
     */
    private void confirmPendingPairing() {
        preferences.setAppliancePairing(pendingApi, pendingToken);
        setServerAddress(pendingHostPort);
        setStep(Step.READY);
    }

    /**
     * The appliance's "Phone control" QR encodes a JSON object
     * {"lms": "<url or host:port>", "api": "<host:port>", "token": "<pairing token>"}
     * (see sources_server.py's /api/pair/token and Settings.jsx). Returns null for
     * older/plain QR content (a bare URL or host:port), which callers should treat
     * as the LMS address directly.
     */
    private static org.json.JSONObject parsePairingJson(String content) {
        if (content == null) {
            return null;
        }
        content = content.trim();
        if (!content.startsWith("{")) {
            return null;
        }
        try {
            return new org.json.JSONObject(content);
        } catch (org.json.JSONException e) {
            return null;
        }
    }

    /**
     * Extracts a "host:port" (or bare host) string from scanned QR content. The
     * appliance's own QR codes (e.g. Settings -> Phone control) encode a full URL
     * like "http://192.168.1.50:9000/material/"; a plain "host" or "host:port" QR
     * is also accepted as-is.
     */
    private static String parseHostPortFromQr(String content) {
        if (content == null) {
            return null;
        }
        content = content.trim();
        if (content.isEmpty()) {
            return null;
        }
        if (content.matches("(?i)^[a-z][a-z0-9+.-]*://.*")) {
            try {
                URI uri = URI.create(content);
                String host = uri.getHost();
                if (host == null) {
                    return null;
                }
                int port = uri.getPort();
                return port > 0 ? (host + ":" + port) : host;
            } catch (Exception e) {
                return null;
            }
        }
        return content;
    }

    private void setServerAddress(String address) {
        serverAddress = preferences.getServerAddress(address);

        serverAddressEditText.setText(serverAddress.localAddress());
        userNameEditText.setText(serverAddress.userName);
        passwordEditText.setText(serverAddress.password);
        wakeOnLan.setChecked(serverAddress.wakeOnLan);
        macLayout.setVisibility(serverAddress.wakeOnLan ? VISIBLE : GONE);
        macEditText.setText(Util.formatMac(serverAddress.mac));
    }
}
