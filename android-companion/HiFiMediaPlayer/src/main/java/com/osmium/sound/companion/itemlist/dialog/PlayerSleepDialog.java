package com.osmium.sound.companion.itemlist.dialog;

import android.app.Dialog;
import android.os.Bundle;
import android.text.InputType;

import androidx.annotation.NonNull;

import com.osmium.sound.companion.Preferences;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.Util;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.service.ISqueezeService;

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
