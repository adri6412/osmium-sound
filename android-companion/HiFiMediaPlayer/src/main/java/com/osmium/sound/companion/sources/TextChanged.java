package com.osmium.sound.companion.sources;

import android.text.Editable;
import android.text.TextWatcher;

/** A TextWatcher that only cares that the text changed. */
public final class TextChanged implements TextWatcher {
    private final Runnable onChange;

    public TextChanged(Runnable onChange) {
        this.onChange = onChange;
    }

    @Override
    public void beforeTextChanged(CharSequence s, int start, int count, int after) {
    }

    @Override
    public void onTextChanged(CharSequence s, int start, int before, int count) {
    }

    @Override
    public void afterTextChanged(Editable s) {
        onChange.run();
    }
}
