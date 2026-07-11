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

package com.hifi.mediaplayer.dialog;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.CountDownTimer;
import android.text.Editable;
import android.util.AttributeSet;
import android.widget.ArrayAdapter;
import android.widget.AutoCompleteTextView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.textfield.TextInputLayout;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;

import com.osmium.sound.companion.Preferences;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.Util;
import com.osmium.sound.companion.util.AfterTextChangedLister;
import com.osmium.sound.companion.util.ScanNetworkTask;

/**
 * Scans the local network for servers, allow the user to choose one, set it as the preferred server
 * for this network, and optionally enter authentication information.
 * <p>
 * A new network scan can be initiated manually if desired.
 */
public class ServerAddressView extends LinearLayout implements ScanNetworkTask.ScanNetworkCallback {
    private Preferences preferences;
    private Preferences.ServerAddress serverAddress;

    private AutoCompleteTextView serverAddressEditText;
    private TextInputLayout serversSpinner_til;
    private AutoCompleteTextView serversSpinner;
    private EditText userNameEditText;
    private EditText passwordEditText;
    private MaterialCheckBox wakeOnLan;
    private TextInputLayout macLayout;
    private boolean macDirty;
    private EditText macEditText;
    private ProgressBar scanProgress;

    private ScanNetworkTask scanNetworkTask;

    /** Map server names to IP addresses. */
    private Map<String, String> discoveredServers;

    private boolean isManual;
    private OnClickListener startNetWorkScan;

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
                serverAddressEditText.setAdapter(new ArrayAdapter<>(getContext(), R.layout.dropdown_item, preferences.getServerHistory()));
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

                scanProgress = findViewById(R.id.scan_progress);

                // Set up the servers spinner.
                serversSpinner_til = findViewById(R.id.found_servers_til);
                serversSpinner = findViewById(R.id.found_servers);
                serversSpinner.setAdapter(new ArrayAdapter<>(getContext(), R.layout.dropdown_item));

                setEditServerAddressAvailability();
                setServerAddress(serverAddress.localAddress());

                startNetworkScan();
                startNetWorkScan = v -> startNetworkScan();
                serversSpinner_til.setStartIconOnClickListener(startNetWorkScan);
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
        serverAddress.setAddress(address);
        serverAddress.setServerName(getServerName(address));
        serverAddress.userName = userNameEditText.getText().toString();
        serverAddress.password = passwordEditText.getText().toString();
        serverAddress.wakeOnLan = wakeOnLan.isChecked();
        serverAddress.mac = Util.parseMac(macEditText.getText().toString());
        preferences.saveServerAddress(serverAddress);

        return true;
    }

    /**
     * Launches the ZXing scanner activity to read the QR code shown on the appliance
     * (Settings -> Phone control). Camera permission is requested by the scanner
     * activity itself if needed. Uses the classic startActivityForResult-based
     * IntentIntegrator (not the newer Activity Result API) because ServerAddressView
     * is a plain View inflated asynchronously — it has no safe point to register an
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
     * fill in the server address field. Returns true if the result was consumed
     * (i.e. it was a scan result at all, scanned or cancelled).
     */
    public boolean handleActivityResult(int requestCode, int resultCode, Intent data) {
        IntentResult result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data);
        if (result == null) {
            return false;
        }
        String contents = result.getContents();
        if (contents == null) {
            return true; // user cancelled the scan
        }
        String hostPort = parseHostPortFromQr(contents);
        if (hostPort == null) {
            Toast.makeText(getContext(), R.string.settings_scan_qr_failed, Toast.LENGTH_LONG).show();
            return true;
        }
        isManual = true;
        setEditServerAddressAvailability();
        setServerAddress(hostPort);
        return true;
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

    @Override
    protected void onDetachedFromWindow() {
        // Stop scanning
        if (scanNetworkTask != null) {
            scanNetworkTask.cancel();
        }

        super.onDetachedFromWindow();
    }

    /**
     * Starts scanning for servers.
     */
    private void startNetworkScan() {
        scanProgress.setVisibility(VISIBLE);
        serversSpinner_til.setStartIconDrawable(android.R.color.transparent);
        serversSpinner_til.setStartIconOnClickListener(null);
        serversSpinner.setText(R.string.settings_server_scan_progress);
        scanNetworkTask = new ScanNetworkTask(getContext(), this);
        new Thread(scanNetworkTask).start();

        scanProgress.setProgress(0);
        new CountDownTimer(ScanNetworkTask.DISCOVERY_ATTEMPT_TIMEOUT, 50) {
            @Override
            public void onTick(long millisUntilFinished) {
                scanProgress.setProgress((int) (100 * (ScanNetworkTask.DISCOVERY_ATTEMPT_TIMEOUT - millisUntilFinished) / ScanNetworkTask.DISCOVERY_ATTEMPT_TIMEOUT));
            }

            @Override
            public void onFinish() {
            }
        }.start();
    }

    /**
     * Called when server scanning has finished.
     * @param serverMap Discovered servers, key is the server name, value is the IP address.
     */
    public void onScanFinished(Map<String, String> serverMap) {
        scanNetworkTask = null;

        scanProgress.setVisibility(INVISIBLE);
        serversSpinner_til.setStartIconDrawable(R.drawable.ic_refresh);
        serversSpinner_til.setStartIconOnClickListener(startNetWorkScan);

        discoveredServers = serverMap;

        List<String> keys = new ArrayList<>(discoveredServers.keySet());
        keys.add(getContext().getString(R.string.settings_manual_server_addr));
        serversSpinner.setAdapter(new ArrayAdapter<>(getContext(), R.layout.dropdown_item, keys));

        // First look for the stored server name in the list of found servers
        String addressOfStoredServerName = discoveredServers.get(serverAddress.serverName());
        int position = getServerPosition(addressOfStoredServerName);

        // If that fails, look for the stored server address in the list of found servers
        if (position < 0) {
            position = getServerPosition(serverAddress.localAddress());
        }

        // This shouldn't happen, but crash reports say that it does
        if (keys.size() > 0) {
            serversSpinner.setText(keys.get(position < 0 ? keys.size() - 1 : position), false);
        }
        isManual = (position < 0);
        setEditServerAddressAvailability();

        serversSpinner.setOnItemClickListener((parent, view, pos, id) -> {
            String serverAddress = discoveredServers.get((String) ((TextView)view).getText());
            isManual = (pos == parent.getCount() - 1);
            setEditServerAddressAvailability();
            setServerAddress(serverAddress);
        });
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

    private void setEditServerAddressAvailability() {
        if (discoveredServers == null || discoveredServers.isEmpty()) {
            serverAddressEditText.setEnabled(true);
        } else {
            serverAddressEditText.setEnabled(isManual);
        }
    }

    private String getServerName(String ipPort) {
        if (discoveredServers != null)
            for (Entry<String, String> entry : discoveredServers.entrySet())
                if (ipPort.equals(entry.getValue()))
                    return entry.getKey();
        return null;
    }

    private int getServerPosition(String host) {
        if (host != null && discoveredServers != null) {
            int position = 0;
            for (Entry<String, String> entry : discoveredServers.entrySet()) {
                if (host.equals(entry.getValue()))
                    return position;
                position++;
            }
        }
        return -1;
    }

}
