package com.hifi.mediaplayer.itemlist.dialog;

import android.app.Dialog;
import android.os.Bundle;
import androidx.annotation.NonNull;
import android.text.InputType;

import com.hifi.mediaplayer.R;
import com.hifi.mediaplayer.itemlist.PlayerListActivity;

public class PlayerRenameDialog extends BaseEditTextDialog {

    private PlayerListActivity activity;

    @NonNull
    @Override
    public Dialog onCreateDialog(Bundle savedInstanceState) {
        Dialog dialog = super.onCreateDialog(savedInstanceState);

        activity = (PlayerListActivity) getActivity();
        dialog.setTitle(getString(R.string.rename_title, activity.getCurrentPlayer().getName()));
        editText.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        editText.setText(activity.getCurrentPlayer().getName());

        return dialog;
    }

    @Override
    protected boolean commit(String newName) {
        activity.playerRename(newName);
        return true;
    }

}
