package com.osmium.sound.companion.sources;

import android.content.Context;

import java.util.Locale;

import com.osmium.sound.companion.R;

/** Disk sizes as the web admin's SourcesPanel.vue prints them (fmtSize / fmtBytes). */
public final class SourcesFormat {
    private static final double GB = 1024d * 1024d * 1024d;

    private SourcesFormat() {}

    private static double toGb(Object value) {
        if (value instanceof Number) return ((Number) value).doubleValue() / GB;
        if (value instanceof String) {
            try {
                return Double.parseDouble((String) value) / GB;
            } catch (NumberFormatException e) {
                return Double.NaN;
            }
        }
        return Double.NaN;
    }

    /**
     * Whole GB (or TB with one decimal) — for a disk's capacity. A value that is
     * not a byte count (lsblk's human-readable "32G") is shown as it is.
     */
    public static String size(Context context, Object value) {
        double gb = toGb(value);
        if (Double.isNaN(gb)) {
            return value instanceof String ? (String) value : "";
        }
        if (gb <= 0) return "";
        if (gb >= 1000) {
            return context.getString(R.string.sources_size_tb, String.format(Locale.getDefault(), "%.1f", gb / 1024));
        }
        return context.getString(R.string.sources_size_gb, String.valueOf(Math.round(gb)));
    }

    /** Like {@link #size}, with one decimal below 10 GB so a nearly full disk never reads "0 GB". */
    public static String bytes(Context context, Object value) {
        double gb = toGb(value);
        if (Double.isNaN(gb) || Double.isInfinite(gb) || gb <= 0) return "";
        if (gb >= 1000) {
            return context.getString(R.string.sources_size_tb, String.format(Locale.getDefault(), "%.1f", gb / 1024));
        }
        return context.getString(R.string.sources_size_gb, gb >= 10
                ? String.valueOf(Math.round(gb))
                : String.format(Locale.getDefault(), "%.1f", gb));
    }
}
