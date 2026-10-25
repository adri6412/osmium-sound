package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.RadioGroup;
import android.widget.TextView;

/**
 * Whether a mouse pointer is shown on the device's screen — the pointer part of
 * the web admin's Settings → Display card, a screen of its own under Appearance
 * to match the kiosk. Reads /api/system/pointer_status and writes
 * /api/system/pointer_set through the sources_server.py proxy.
 */
public class PointerActivity extends ApplianceSettingsActivity {
    private RadioGroup pointerGroup;
    private TextView pointerUnavailable;
    private boolean pointerEnabled = true;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setUpScreen(R.string.settings_tile_pointer, R.layout.appliance_pointer);

        pointerGroup = findViewById(R.id.display_pointer_group);
        pointerUnavailable = findViewById(R.id.display_pointer_unavailable);

        addRadio(pointerGroup, getString(R.string.appliance_display_pointer_on), true);
        addRadio(pointerGroup, getString(R.string.appliance_display_pointer_off), false);
        pointerGroup.setOnCheckedChangeListener((group, id) -> {
            if (isQuiet()) return;
            Boolean on = (Boolean) checkedTag(group, id);
            if (on != null && on != pointerEnabled) setPointer(on);
        });

        loadPointer();
    }

    private void loadPointer() {
        load("/api/system/pointer_status", "enabled", body -> {
            pointerEnabled = body.optBoolean("enabled", true);
            pointerUnavailable.setVisibility(body.optBoolean("available", true) ? View.GONE : View.VISIBLE);
            checkByTag(pointerGroup, pointerEnabled);
        }, () -> showMessage(getString(R.string.appliance_display_pointer_failed)));
    }

    private void setPointer(boolean on) {
        post("/api/system/pointer_set", json("enable", on), R.string.appliance_display_pointer_failed, body -> {
            pointerEnabled = body.optBoolean("enabled", on);
            checkByTag(pointerGroup, pointerEnabled);
            showMessage(messageOf(body, getString(R.string.appliance_display_pointer_changed)));
        }, () -> checkByTag(pointerGroup, pointerEnabled));
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, PointerActivity.class));
    }
}
