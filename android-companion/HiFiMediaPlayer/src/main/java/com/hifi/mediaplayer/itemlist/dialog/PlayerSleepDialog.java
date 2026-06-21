package com.hifi.mediaplayer.itemlist.dialog;

import android.app.Dialog;
import android.os.Bundle;
import android.text.InputType;

import androidx.annotation.NonNull;

import com.hifi.mediaplayer.Preferences;
import com.hifi.mediaplayer.R;
import com.hifi.mediaplayer.HiFiMediaPlayer;
import com.hifi.mediaplayer.Util;
import com.hifi.mediaplayer.framework.BaseActivity;
import com.hifi.mediaplayer.model.Player;
import com.hifi.mediaplayer.service.ISqueezeService;

public class PlayerSleepDialog extends BaseEditTextDialog {

    private BaseActivity activity;
    private Player player;

    public PlayerSleepDialog(Player player) {
        this.player = player;
    }

    @NonNull
    @Override
    public Dialog onCreateDialog(Bundle savedInstanceState) {
        Dialog dialog = super.onCreateDialog(savedInstanceState);

        activity = (BaseActivity) getActivity();
        editTextLayout.setHint(R.string.set_sleep_timer);
        editTextLayout.setSuffixText(getString(R.string.minutes));
        editText.setInputType(InputType.TYPE_CLASS_NUMBER);
        editText.setText(String.valueOf(HiFiMediaPlayer.getPreferences().getSleepMinutes()));

        return dialog;
    }

    @Override
    protected boolean commit(String sleep) {
        ISqueezeService service = activity.getService();
        if (service == null) return false;

        int minutes = (int) Util.parseDecimalInt(sleep, -1);
        if (minutes <= 0) return false;

        service.sleep(player, minutes*60);
        HiFiMediaPlayer.getPreferences().setSleepMinutes(minutes);
        return true;
    }

}
