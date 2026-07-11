package com.osmium.sound.companion.util;

import android.content.Context;

import com.osmium.sound.companion.Preferences;
import com.osmium.sound.companion.HiFiMediaPlayer;

public class DevicePlayers {

    private final Context context;
    private SqueezePlayer squeezePlayer;

    public DevicePlayers(Context context) {
        this.context = context;
    }

    public void onCreate() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        SqueezeLite squeezeLite = new SqueezeLite(context);
        if (preferences.controlSqueezelite() && squeezeLite.has()) squeezeLite.start();
    }

    public void onResume() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        squeezePlayer = (preferences.controlSqueezePlayer() && SqueezePlayer.has(context)) ? SqueezePlayer.startControllingSqueezePlayer(context) : null;
    }

    public void onPause() {
        if (squeezePlayer != null) {
            squeezePlayer.stopControllingSqueezePlayer();
            squeezePlayer = null;
        }
    }

}
