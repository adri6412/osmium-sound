package com.osmium.sound.companion.dialog;

import android.app.Dialog;
import android.os.Bundle;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.Spinner;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.fragment.app.DialogFragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.model.PlayerState;
import com.osmium.sound.companion.service.ISqueezeService;

/**
 * Transition (crossfade/gapless) type + duration, ReplayGain mode, and the
 * fixed-volume-100%/bit-perfect toggle for the active player — mirrors the
 * Electron UI's "Playback" settings section.
 * Reads/writes via the existing LMS `playerpref` mechanism (Player.Pref +
 * ISqueezeService#playerPref), not the appliance HTTP API: these are LMS
 * server prefs, already tracked for the active player by the periodic
 * status poll (see CometClient's serverStatusRequest()).
 * <p>
 * digitalVolumeControl is also independently exposed by VolumeSettings (the
 * legacy "Volume Control" dialog, framed in LMS's own on/off terminology) —
 * both write the same server pref, so either screen changing it is visible
 * from the other; no separate state to keep in sync.
 * <p>
 * The caller must supply the {@link ISqueezeService} via {@link #show}: this
 * dialog can be opened from screens that are not a {@code BaseActivity}
 * (e.g. SettingsFragment, hosted in the plain-AppCompatActivity
 * SettingsActivity), so it can't get the service by casting the host
 * Activity the way BottomSheetDialogFragmentWithService-based dialogs do.
 */
public class PlaybackPrefsDialog extends DialogFragment {
    private static final String[] TRANSITION_VALUES = {"0", "1", "2", "3", "4"};
    private static final String[] REPLAYGAIN_VALUES = {"0", "1", "2", "3"};

    private ISqueezeService service;

    public static void show(androidx.fragment.app.FragmentManager fragmentManager, ISqueezeService service) {
        PlaybackPrefsDialog dialog = new PlaybackPrefsDialog();
        dialog.service = service;
        dialog.show(fragmentManager, "PlaybackPrefsDialog");
    }

    @NonNull
    @Override
    public Dialog onCreateDialog(Bundle savedInstanceState) {
        if (service == null) {
            // Can happen if the dialog is recreated after process death without
            // going through show(); nothing useful to show without a service.
            return new MaterialAlertDialogBuilder(requireActivity())
                    .setTitle(R.string.settings_category_playback)
                    .setMessage(R.string.settings_playback_no_player)
                    .setPositiveButton(android.R.string.ok, null)
                    .create();
        }
        Player player = service.getActivePlayer();
        PlayerState playerState = service.getActivePlayerState();

        android.view.View view = requireActivity().getLayoutInflater().inflate(R.layout.dialog_playback_prefs, null);

        Spinner transitionType = view.findViewById(R.id.playback_transition_type);
        transitionType.setAdapter(new ArrayAdapter<>(requireContext(), android.R.layout.simple_spinner_dropdown_item,
                getResources().getStringArray(R.array.settings_playback_transition_labels)));

        EditText transitionDuration = view.findViewById(R.id.playback_transition_duration);

        Spinner replayGainMode = view.findViewById(R.id.playback_replaygain_mode);
        replayGainMode.setAdapter(new ArrayAdapter<>(requireContext(), android.R.layout.simple_spinner_dropdown_item,
                getResources().getStringArray(R.array.settings_playback_replaygain_labels)));

        // digitalVolumeControl: "1" (default) = LMS applies its own adjustable
        // digital volume; "0" = output fixed at 100%, required for bit-perfect
        // passthrough. Same pref/semantics as the Electron kiosk's toggle.
        SwitchMaterial fixedVolume = view.findViewById(R.id.playback_fixed_volume);

        if (playerState != null) {
            transitionType.setSelection(indexOf(TRANSITION_VALUES, playerState.prefs.get(Player.Pref.TRANSITION_TYPE), 0));
            transitionDuration.setText(orDefault(playerState.prefs.get(Player.Pref.TRANSITION_DURATION), "4"));
            replayGainMode.setSelection(indexOf(REPLAYGAIN_VALUES, playerState.prefs.get(Player.Pref.REPLAY_GAIN_MODE), 0));
            fixedVolume.setChecked("0".equals(playerState.prefs.get(Player.Pref.DIGITAL_VOLUME_CONTROL)));
        }

        boolean hasPlayer = player != null;
        transitionType.setEnabled(hasPlayer);
        transitionDuration.setEnabled(hasPlayer);
        replayGainMode.setEnabled(hasPlayer);
        fixedVolume.setEnabled(hasPlayer);

        MaterialAlertDialogBuilder builder = new MaterialAlertDialogBuilder(requireActivity());
        builder.setTitle(R.string.settings_category_playback)
                .setView(view)
                .setPositiveButton(android.R.string.ok, (dialog, id) -> {
                    if (!hasPlayer) {
                        Toast.makeText(requireContext(), R.string.settings_playback_no_player, Toast.LENGTH_SHORT).show();
                        return;
                    }
                    service.playerPref(Player.Pref.TRANSITION_TYPE, TRANSITION_VALUES[transitionType.getSelectedItemPosition()]);
                    service.playerPref(Player.Pref.TRANSITION_DURATION, transitionDuration.getText().toString());
                    service.playerPref(Player.Pref.REPLAY_GAIN_MODE, REPLAYGAIN_VALUES[replayGainMode.getSelectedItemPosition()]);
                    service.playerPref(Player.Pref.DIGITAL_VOLUME_CONTROL, fixedVolume.isChecked() ? "0" : "1");
                })
                .setNegativeButton(android.R.string.cancel, null);
        return builder.create();
    }

    private static int indexOf(String[] values, String value, int fallback) {
        if (value == null) return fallback;
        for (int i = 0; i < values.length; i++) {
            if (values[i].equals(value)) return i;
        }
        return fallback;
    }

    private static String orDefault(String value, String def) {
        return value != null ? value : def;
    }
}
