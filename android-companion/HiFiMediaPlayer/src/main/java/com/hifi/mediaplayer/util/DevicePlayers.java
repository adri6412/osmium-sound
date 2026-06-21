package com.hifi.mediaplayer.util;

import android.content.Context;

import com.hifi.mediaplayer.Preferences;
import com.hifi.mediaplayer.HiFiMediaPlayer;

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
