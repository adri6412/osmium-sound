package com.hifi.mediaplayer.service;

import android.content.Context;

import com.hifi.mediaplayer.R;

public class PlayerNotFoundException extends Exception {
    public PlayerNotFoundException(Context context) {
        super(context.getString(R.string.NO_PLAYER_FOUND));
    }
}
