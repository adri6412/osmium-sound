package com.hifi.mediaplayer.itemlist.dialog;

import android.content.Context;

import androidx.annotation.StringRes;

import com.hifi.mediaplayer.R;
import com.hifi.mediaplayer.framework.EnumWithText;

/**
 * Supported list layouts.
 */
public enum ArtworkListLayout implements EnumWithText {
    grouped(R.string.settings_layout_grouped),
    grid(R.string.SWITCH_TO_GALLERY),
    list(R.string.SWITCH_TO_EXTENDED_LIST);

    /**
     * The text to use for this layout
     */
    @StringRes
    private final int stringResource;

    @Override
    public String getText(Context context) {
        return context.getString(stringResource);
    }

    ArtworkListLayout(@StringRes int serverString) {
        this.stringResource = serverString;
    }
}
