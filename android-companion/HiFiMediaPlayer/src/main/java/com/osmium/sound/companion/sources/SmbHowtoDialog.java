package com.osmium.sound.companion.sources;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.TextView;

import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONObject;

import com.osmium.sound.companion.R;

/**
 * "How do I reach this shared folder?" — the address, login and step-by-step
 * for Windows or macOS. Mirrors the howto popup in the web admin's
 * SourcesPanel.vue.
 */
public final class SmbHowtoDialog {
    private SmbHowtoDialog() {}

    /** Address to hand out: the IP when known (works without mDNS), otherwise the .local name. */
    public static String host(JSONObject smbCard) {
        if (smbCard == null) return "";
        String ip = SourcesApi.str(smbCard, "ip");
        return ip.isEmpty() ? SourcesApi.str(smbCard, "host") : ip;
    }

    /** The .local name, shown as a second choice only when it differs from the address above. */
    public static String altHost(JSONObject smbCard) {
        if (smbCard == null) return "";
        String ip = SourcesApi.str(smbCard, "ip");
        String host = SourcesApi.str(smbCard, "host");
        return !ip.isEmpty() && !host.isEmpty() && !ip.equals(host) ? host : "";
    }

    public static String winPath(String host, String name) {
        return "\\\\" + host + "\\" + name;
    }

    public static String macPath(String host, String name) {
        return "smb://" + host + "/" + name;
    }

    public static void show(Context context, JSONObject smbCard, String shareName) {
        View view = LayoutInflater.from(context).inflate(R.layout.sources_dialog_howto, null);
        ((TextView) view.findViewById(R.id.sources_howto_intro))
                .setText(context.getString(R.string.sources_smb_howto_intro, shareName));
        MaterialButtonToggleGroup osGroup = view.findViewById(R.id.sources_howto_os);
        TextView details = view.findViewById(R.id.sources_howto_details);
        TextView steps = view.findViewById(R.id.sources_howto_steps);
        TextView tip = view.findViewById(R.id.sources_howto_tip);

        Runnable render = () -> {
            boolean win = osGroup.getCheckedButtonId() != R.id.sources_howto_mac;
            String host = host(smbCard);
            String alt = altHost(smbCard);
            String path = win ? winPath(host, shareName) : macPath(host, shareName);

            StringBuilder d = new StringBuilder();
            d.append(context.getString(R.string.sources_smb_howto_path)).append(": ").append(path);
            if (!alt.isEmpty()) {
                d.append('\n').append(context.getString(R.string.sources_smb_howto_path_alt)).append(": ")
                        .append(win ? winPath(alt, shareName) : macPath(alt, shareName));
            }
            d.append('\n').append(context.getString(R.string.sources_smb_share_user)).append(": ")
                    .append(SourcesApi.str(smbCard, "username"));
            d.append('\n').append(context.getString(R.string.sources_smb_share_pass)).append(": ")
                    .append(SourcesApi.str(smbCard, "password"));
            details.setText(d);

            int[] keys = win
                    ? new int[]{R.string.sources_smb_howto_win1, R.string.sources_smb_howto_win2,
                                R.string.sources_smb_howto_win3}
                    : new int[]{R.string.sources_smb_howto_mac1, R.string.sources_smb_howto_mac2,
                                R.string.sources_smb_howto_mac3, R.string.sources_smb_howto_mac4};
            StringBuilder s = new StringBuilder();
            for (int i = 0; i < keys.length; i++) {
                if (i > 0) s.append("\n\n");
                // Only some steps take the address; extra format args are ignored.
                s.append(i + 1).append(". ").append(context.getString(keys[i], path));
            }
            steps.setText(s);
            tip.setText(win ? R.string.sources_smb_regenerate_hint : R.string.sources_smb_howto_mac_tip);
        };

        osGroup.check(R.id.sources_howto_win);
        osGroup.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) render.run();
        });
        render.run();

        new MaterialAlertDialogBuilder(context)
                .setTitle(R.string.sources_smb_howto_title)
                .setView(view)
                .setPositiveButton(R.string.sources_common_close, null)
                .show();
    }
}
