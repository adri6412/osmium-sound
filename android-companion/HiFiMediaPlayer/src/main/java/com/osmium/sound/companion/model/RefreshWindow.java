package com.osmium.sound.companion.model;

public enum RefreshWindow {
    refreshMe,
    refreshOrigin,
    refreshGrandparent;

    public static RefreshWindow fromString(String s) {
        return (s == null ? null : RefreshWindow.valueOf(s));
    }
}
