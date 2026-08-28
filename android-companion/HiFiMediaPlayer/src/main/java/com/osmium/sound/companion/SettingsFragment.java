package com.osmium.sound.companion;

import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.ServiceConnection;
import android.content.SharedPreferences;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.widget.ListView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.core.os.LocaleListCompat;
import androidx.fragment.app.DialogFragment;
import androidx.preference.CheckBoxPreference;
import androidx.preference.EditTextPreference;
import androidx.preference.ListPreference;
import androidx.preference.Preference;
import androidx.preference.PreferenceFragmentCompat;
import androidx.preference.SwitchPreferenceCompat;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.dialog.CallStateDialog;
import com.osmium.sound.companion.download.DownloadFilenameStructure;
import com.osmium.sound.companion.download.DownloadPathStructure;
import com.osmium.sound.companion.framework.EnumWithText;
import com.osmium.sound.companion.model.PlayableItemAction;
import com.osmium.sound.companion.service.ISqueezeService;
import com.osmium.sound.companion.service.SqueezeService;
import com.osmium.sound.companion.util.Scrobble;
import com.osmium.sound.companion.util.SqueezeLite;
import com.osmium.sound.companion.util.SqueezePlayer;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.CallStatePermissionLauncher;

public class SettingsFragment  extends PreferenceFragmentCompat implements
        Preference.OnPreferenceChangeListener, SharedPreferences.OnSharedPreferenceChangeListener,
        CallStateDialog.CallStateDialogHost {

    private final String TAG = "SettingsFragment";

    private static final String KEY_OSMIUM_SOUND = "squeezer.osmium_sound";
    private static final String KEY_LYRION_SKIN = "squeezer.lyrion_skin.open";

    // Progress polling for the web-player skin change (see
    // fillLyrionSkinPreferences): 1.5s like the kiosk/webui, bounded so a
    // job that never reports done/error can't keep this fragment polling for
    // ever. Installing Material + restarting Lyrion normally takes well under
    // a minute; 6 minutes is generous.
    private static final long SKIN_POLL_INTERVAL_MS = 1500;
    private static final int SKIN_POLL_MAX = 240;
    private final Handler skinPollHandler = new Handler(Looper.getMainLooper());
    private String skinChoice = "unset";
    private int skinPollCount;

    private ISqueezeService service = null;

    private IntEditTextPreference fadeInPref;

    private final ServiceConnection serviceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            SettingsFragment.this.service = (ISqueezeService) service;
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            service = null;
        }
    };

    @Override
    public void onCreatePreferences(Bundle savedInstanceState, String rootKey) {
        getActivity().bindService(new Intent(getActivity(), SqueezeService.class), serviceConnection,
                Context.BIND_AUTO_CREATE);
        Log.d(TAG, "did bindService; service = " + service);

        getPreferenceManager().setSharedPreferencesName(Preferences.NAME);
        setPreferencesFromResource(R.xml.preferences, rootKey);

        // The "Osmium Sound" screen is a nested PreferenceScreen: when opened,
        // rootKey scopes findPreference() to just its own children, so only
        // wire up the preferences that actually live under it.
        if (KEY_OSMIUM_SOUND.equals(rootKey)) {
            fillBackupPreferences();
            fillAudioOutputPreferences();
            fillUpdatesPreferences();
            fillSystemAdminPreferences();
            fillMultiroomPreferences();
            return;
        }

        SharedPreferences sharedPreferences = getPreferenceManager().getSharedPreferences();
        sharedPreferences.registerOnSharedPreferenceChangeListener(this);
        Preferences preferences = new Preferences(getActivity(), sharedPreferences);

        fadeInPref = requirePreference(Preferences.KEY_FADE_IN_SECS);
        fadeInPref.setOnPreferenceChangeListener(this);
        updateFadeInSecondsSummary(preferences.getFadeInSecs());

        fillIncomingCallPreferences(preferences);

        fillDisplayPreferences(preferences);

        fillNowPlayingPreferences(preferences);

        fillUserInterfacePreferences(preferences);

        fillScrobblePreferences(sharedPreferences);
        fillLocalPlayerPreferences(preferences);
        fillDevicePlayerPreferences(preferences);

        fillDownloadPreferences(preferences);

        fillPlaybackPreferences();
        fillLyrionRescanPreferences();
        fillLyrionSkinPreferences();

        applyServerKind(preferences);
    }

    /**
     * The appliance settings only mean anything against an Osmium Sound device:
     * on a plain Lyrion server there is no appliance API behind them, so they
     * are hidden rather than left to fail when tapped. Which server this is was
     * decided in the connection wizard.
     */
    private void applyServerKind(Preferences preferences) {
        boolean osmium = preferences.isOsmiumAppliance();
        Preference osmiumScreen = requirePreference(KEY_OSMIUM_SOUND);
        if (osmiumScreen != null) osmiumScreen.setVisible(osmium);
        if (!osmium) {
            // The web player skin also lives on the appliance's own service.
            Preference skin = requirePreference(KEY_LYRION_SKIN);
            if (skin != null) skin.setVisible(false);
        }
    }

    // DSP/EQ is deliberately not wired up here — held back for a future paid
    // tier, same as the kiosk and admin-webui (see commit 1dd7868).
    // DspSettingsActivity stays intact and reachable by class name only.

    private void fillBackupPreferences() {
        Preference pref = requirePreference("squeezer.backup.open");
        pref.setOnPreferenceClickListener(preference -> {
            BackupRestoreActivity.show(requireActivity());
            return true;
        });
    }

    private void fillAudioOutputPreferences() {
        Preference pref = requirePreference("squeezer.audio_output.open");
        pref.setOnPreferenceClickListener(preference -> {
            AudioOutputActivity.show(requireActivity());
            return true;
        });
    }

    private void fillPlaybackPreferences() {
        Preference pref = requirePreference("squeezer.playback.open");
        pref.setOnPreferenceClickListener(preference -> {
            if (service != null) {
                com.osmium.sound.companion.dialog.PlaybackPrefsDialog.show(getParentFragmentManager(), service);
            }
            return true;
        });
    }

    private void fillLyrionRescanPreferences() {
        Preference pref = requirePreference("squeezer.lyrion_rescan.open");
        pref.setOnPreferenceClickListener(preference -> {
            if (service != null) {
                service.rescanLibrary();
                Toast.makeText(getContext(), R.string.settings_lyrion_rescan_started, Toast.LENGTH_SHORT).show();
            }
            return true;
        });
    }

    // ── LMS web player skin (Osmium / Material) ─────────────────────────
    // Mirrors the chooser the kiosk (Settings.jsx, "Lyrion" section) and the
    // admin-webui (Settings.vue, same section) offer. It lives on
    // sources_server itself (/api/lms_skin, /api/lms_skin_status — not behind
    // the /api/system/* proxy), reached with the same pairing token. The
    // entry hides itself when the appliance can't answer: older bundle without
    // the route, not paired yet, or no local Lyrion to skin (external server).

    private void fillLyrionSkinPreferences() {
        Preference pref = requirePreference(KEY_LYRION_SKIN);
        pref.setOnPreferenceClickListener(preference -> {
            showLyrionSkinDialog(pref);
            return true;
        });
        loadLyrionSkin(pref);
    }

    private void loadLyrionSkin(Preference pref) {
        ApplianceHttpClient.getJson("/api/lms_skin", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!isAdded()) return;
                if (!body.optBoolean("success", false) || !body.optBoolean("lms_installed", false)) {
                    pref.setVisible(false);
                    return;
                }
                skinChoice = body.optString("skin", "unset");
                pref.setSummary(getString(R.string.settings_lyrion_skin_summary) + "\n"
                        + getString(R.string.settings_lyrion_skin_current, skinLabel(skinChoice)));
                pref.setEnabled(true);
                pref.setVisible(true);
            }

            @Override
            public void onFailure(String message) {
                if (!isAdded()) return;
                pref.setVisible(false);
            }
        });
    }

    private String skinLabel(String skin) {
        if ("osmium".equals(skin)) return getString(R.string.settings_lyrion_skin_osmium);
        if ("material".equals(skin)) return getString(R.string.settings_lyrion_skin_material);
        return getString(R.string.settings_lyrion_skin_unset);
    }

    private void showLyrionSkinDialog(Preference pref) {
        final String[] values = {"osmium", "material"};
        final CharSequence[] labels = {
                getString(R.string.settings_lyrion_skin_osmium),
                getString(R.string.settings_lyrion_skin_material)};
        int current = "material".equals(skinChoice) ? 1 : ("osmium".equals(skinChoice) ? 0 : -1);
        final int[] picked = {current};
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.settings_lyrion_skin_title)
                .setSingleChoiceItems(labels, current, (dialog, which) -> picked[0] = which)
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> {
                    if (picked[0] < 0 || values[picked[0]].equals(skinChoice)) return;
                    applyLyrionSkin(pref, values[picked[0]]);
                })
                .show();
    }

    private void applyLyrionSkin(Preference pref, String skin) {
        JSONObject payload = new JSONObject();
        try {
            payload.put("skin", skin);
        } catch (JSONException ignored) {
        }
        pref.setEnabled(false);
        pref.setSummary(R.string.settings_lyrion_skin_applying);
        ApplianceHttpClient.postJson("/api/lms_skin", payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!isAdded()) return;
                if (!body.optBoolean("started", false)) {
                    // Refused (busy, no local Lyrion, bad token...) — the
                    // appliance's message says why; the choice on disk is unchanged.
                    Toast.makeText(getContext(),
                            body.optString("message", getString(R.string.settings_lyrion_skin_failed)),
                            Toast.LENGTH_LONG).show();
                    loadLyrionSkin(pref);
                    return;
                }
                skinChoice = skin;
                skinPollCount = 0;
                pollLyrionSkinStatus(pref);
            }

            @Override
            public void onFailure(String message) {
                if (!isAdded()) return;
                Toast.makeText(getContext(), getString(R.string.settings_lyrion_skin_failed), Toast.LENGTH_LONG).show();
                loadLyrionSkin(pref);
            }
        });
    }

    private void pollLyrionSkinStatus(Preference pref) {
        skinPollHandler.removeCallbacksAndMessages(null);
        if (++skinPollCount > SKIN_POLL_MAX) {
            Toast.makeText(getContext(), getString(R.string.settings_lyrion_skin_failed), Toast.LENGTH_LONG).show();
            loadLyrionSkin(pref);
            return;
        }
        skinPollHandler.postDelayed(() -> ApplianceHttpClient.getJson("/api/lms_skin_status",
                new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (!isAdded()) return;
                String state = body.optString("state", "");
                if ("done".equals(state) || "error".equals(state)) {
                    Toast.makeText(getContext(), "done".equals(state)
                            ? getString(R.string.settings_lyrion_skin_changed)
                            : body.optString("message", getString(R.string.settings_lyrion_skin_failed)),
                            Toast.LENGTH_LONG).show();
                    loadLyrionSkin(pref);
                    return;
                }
                pref.setSummary("installing".equals(state)
                        ? R.string.settings_lyrion_skin_installing
                        : R.string.settings_lyrion_skin_applying);
                pollLyrionSkinStatus(pref);
            }

            @Override
            public void onFailure(String message) {
                if (!isAdded()) return;
                // One dropped poll (Wi-Fi hiccup) is not a verdict — keep watching.
                pollLyrionSkinStatus(pref);
            }
        }), SKIN_POLL_INTERVAL_MS);
    }

    private void fillUpdatesPreferences() {
        Preference pref = requirePreference("squeezer.updates.open");
        pref.setOnPreferenceClickListener(preference -> {
            UpdatesActivity.show(requireActivity());
            return true;
        });
    }

    private void fillSystemAdminPreferences() {
        Preference pref = requirePreference("squeezer.system_admin.open");
        pref.setOnPreferenceClickListener(preference -> {
            SystemAdminActivity.show(requireActivity());
            return true;
        });
    }

    private void fillMultiroomPreferences() {
        Preference pref = requirePreference("squeezer.multiroom.open");
        pref.setOnPreferenceClickListener(preference -> {
            MultiroomActivity.show(requireActivity());
            return true;
        });
    }

    private void fillScrobblePreferences(SharedPreferences preferences) {
        SwitchPreferenceCompat scrobblePref = requirePreference(Preferences.KEY_SCROBBLE_ENABLED);
        scrobblePref.setOnPreferenceChangeListener(this);

        if (!Scrobble.canScrobble()) {
            scrobblePref.setSummaryOff(getString(R.string.settings_scrobble_noapp));
            scrobblePref.setChecked(false);
        } else {
            scrobblePref.setSummaryOff(getString(R.string.settings_scrobble_off));

            scrobblePref
                    .setChecked(preferences.getBoolean(Preferences.KEY_SCROBBLE_ENABLED, false));

            // If an old KEY_SCROBBLE preference exists, use it, delete it, and
            // upgrade it to the new KEY_SCROBBLE_ENABLED preference.
            if (preferences.contains(Preferences.KEY_SCROBBLE)) {
                boolean enabled = (Integer.parseInt(
                        preferences.getString(Preferences.KEY_SCROBBLE, "0")) > 0);
                scrobblePref.setChecked(enabled);
                SharedPreferences.Editor editor = preferences.edit();
                editor.putBoolean(Preferences.KEY_SCROBBLE_ENABLED, enabled);
                editor.remove(Preferences.KEY_SCROBBLE);
                editor.apply();
            }
        }
    }

    /**
     * Settings for "this phone is a player". Unlike the third-party player hooks
     * below, this one is always shown: it needs nothing installed.
     */
    private void fillLocalPlayerPreferences(Preferences preferences) {
        SwitchPreferenceCompat enabled = requirePreference(Preferences.KEY_LOCAL_PLAYER_ENABLED);
        enabled.setChecked(preferences.isLocalPlayerEnabled());

        EditTextPreference name = requirePreference(Preferences.KEY_LOCAL_PLAYER_NAME);
        name.setText(preferences.getLocalPlayerName());
        name.setOnPreferenceChangeListener(this);

        fillEnumPreference(requirePreference(Preferences.KEY_LOCAL_PLAYER_QUALITY_WIFI),
                Preferences.LocalPlayerQuality.class, preferences.getLocalPlayerQuality(false));
        fillEnumPreference(requirePreference(Preferences.KEY_LOCAL_PLAYER_QUALITY_MOBILE),
                Preferences.LocalPlayerQuality.class, preferences.getLocalPlayerQuality(true));

        if (!hasFlacDecoder()) {
            // Lossless would silently fall back to a transcoded stream, so say so.
            ListPreference wifi = requirePreference(Preferences.KEY_LOCAL_PLAYER_QUALITY_WIFI);
            wifi.setSummary(getString(R.string.settings_local_player_no_flac));
        }
    }

    /** FLAC decoding is only guaranteed from API 27, and this app supports 26. */
    private boolean hasFlacDecoder() {
        try {
            MediaFormat format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_FLAC, 44100, 2);
            return new MediaCodecList(MediaCodecList.REGULAR_CODECS).findDecoderForFormat(format) != null;
        } catch (RuntimeException e) {
            return false;
        }
    }

    private void fillDevicePlayerPreferences(Preferences preferences) {
        SwitchPreferenceCompat switchPreference;

        switchPreference = requirePreference(Preferences.KEY_SQUEEZEPLAYER_ENABLED);
        switchPreference.setVisible(SqueezePlayer.has(getContext()));
        switchPreference.setChecked(preferences.controlSqueezePlayer());

        switchPreference = requirePreference(Preferences.KEY_SQUEEZELITE_ENABLED);
        switchPreference.setVisible(SqueezeLite.has(getContext()));
        switchPreference.setChecked(preferences.controlSqueezelite());
    }

    private void fillDownloadPreferences(Preferences preferences) {
        fillEnumPreference(requirePreference(Preferences.KEY_DOWNLOAD_PATH_STRUCTURE), DownloadPathStructure.class, preferences.getDownloadPathStructure());
        fillEnumPreference(requirePreference(Preferences.KEY_DOWNLOAD_FILENAME_STRUCTURE), DownloadFilenameStructure.class, preferences.getDownloadFilenameStructure());
        updateDownloadPreferences(preferences);
    }

    private void updateDownloadPreferences(Preferences preferences) {
        final SwitchPreferenceCompat downloadEnabled = requirePreference(Preferences.KEY_DOWNLOAD_ENABLED);
        final CheckBoxPreference downloadConfirmation = requirePreference(Preferences.KEY_DOWNLOAD_CONFIRMATION);
        final CheckBoxPreference useServerPathPreference = requirePreference(Preferences.KEY_DOWNLOAD_USE_SERVER_PATH);
        final ListPreference pathStructurePreference = requirePreference(Preferences.KEY_DOWNLOAD_PATH_STRUCTURE);
        final ListPreference filenameStructurePreference = requirePreference(Preferences.KEY_DOWNLOAD_FILENAME_STRUCTURE);
        final boolean enabled = preferences.isDownloadEnabled();
        final boolean useServerPath = preferences.isDownloadUseServerPath();

        downloadEnabled.setChecked(enabled);
        downloadConfirmation.setChecked(preferences.isDownloadConfirmation());
        useServerPathPreference.setChecked(useServerPath);

        downloadConfirmation.setEnabled(enabled);
        useServerPathPreference.setEnabled(enabled);
        pathStructurePreference.setEnabled(enabled && !useServerPath);
        filenameStructurePreference.setEnabled(enabled && !useServerPath);
    }

    private void fillIncomingCallPreferences(Preferences preferences) {
        fillEnumPreference(requirePreference(Preferences.KEY_ACTION_ON_INCOMING_CALL), Preferences.IncomingCallAction.class, preferences.getActionOnIncomingCall());
        updateIncomingCallPreferences(preferences);
    }

    private void updateIncomingCallPreferences(Preferences preferences) {
        this.<CheckBoxPreference>requirePreference(Preferences.KEY_RESTORE_MUSIC_AFTER_CALL).setEnabled(preferences.getActionOnIncomingCall() != Preferences.IncomingCallAction.NONE);
    }

    private void fillDisplayPreferences(Preferences preferences) {
        ListPreference onSelectThemePref = requirePreference(Preferences.KEY_ON_THEME_SELECT_ACTION);
        ArrayList<String> entryValues = new ArrayList<>();
        ArrayList<String> entries = new ArrayList<>();

        for (ThemeManager.Theme theme : ThemeManager.Theme.values()) {
            entryValues.add(theme.name());
            entries.add(theme.getText(requireActivity()));
        }

        onSelectThemePref.setEntryValues(entryValues.toArray(new String[entryValues.size()]));
        onSelectThemePref.setEntries(entries.toArray(new String[0]));
        onSelectThemePref.setDefaultValue(ThemeManager.getDefaultTheme().name());
        if (onSelectThemePref.getValue() == null) {
            onSelectThemePref.setValue(ThemeManager.getDefaultTheme().name());
        } else {
            try {
                ThemeManager.Theme t = ThemeManager.Theme.valueOf(onSelectThemePref.getValue());
            } catch (Exception e) {
                onSelectThemePref.setValue(ThemeManager.getDefaultTheme().name());
            }
        }
        onSelectThemePref.setOnPreferenceChangeListener(this);

        fillLanguagePreference(preferences);

        fillEnumPreference(requirePreference(Preferences.KEY_SCREENSAVER), Preferences.ScreensaverMode.class, preferences.getScreensaverMode());
        fillEnumPreference(requirePreference(Preferences.KEY_FULLSCREEN), Preferences.FullScreenMode.class,preferences.getFullScreenMode());
    }

    /**
     * In-app language picker, mirroring the kiosk's and web admin's language
     * selectors so all three UIs of the product can be switched the same way.
     * <p>
     * The list is intentionally short: only the languages in
     * res/xml/locales_config.xml, i.e. the ones the app is actually fully
     * translated into. Empty value = follow the system.
     * <p>
     * The current value is read back from AppCompatDelegate rather than from
     * SharedPreferences, so the picker still shows the truth when the user
     * changed the language from Android 13+'s own per-app language screen.
     */
    private void fillLanguagePreference(Preferences preferences) {
        ListPreference languagePref = requirePreference(Preferences.KEY_LANGUAGE);
        String[] tags = {"", "it", "en"};
        String[] labels = {
                getString(R.string.settings_language_system),
                "Italiano",
                "English",
        };
        languagePref.setEntryValues(tags);
        languagePref.setEntries(labels);

        LocaleListCompat current = AppCompatDelegate.getApplicationLocales();
        String tag = current.isEmpty() ? "" : current.get(0).getLanguage();
        // A locale we don't offer (e.g. an inherited Squeezer translation still
        // active from an older install) reads as "follow the system".
        languagePref.setValue(Arrays.asList(tags).contains(tag) ? tag : "");

        languagePref.setOnPreferenceChangeListener((preference, newValue) -> {
            String value = String.valueOf(newValue);
            // Answered here = the connection wizard must not ask its language step.
            preferences.setLanguageChosen(true);
            AppCompatDelegate.setApplicationLocales(value.isEmpty()
                    ? LocaleListCompat.getEmptyLocaleList()
                    : LocaleListCompat.forLanguageTags(value));
            return true;
        });
    }

    private void fillNowPlayingPreferences(Preferences preferences) {
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_NOW_PLAYING_VOLUME).setChecked(preferences.nowPlayingVolume());
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_TRACK_COUNT).setChecked(preferences.showTrackCount());
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_TECHNICAL_INFO).setChecked(preferences.showTechnicalInfo());
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_COMPOSER_LINE).setChecked(preferences.addComposerLine());
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_CONDUCTOR_LINE).setChecked(preferences.addConductorLine());
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_CLASSICAL_MUSIC_TAGS).setChecked(preferences.displayClassicalMusicTags());
    }

    private void fillUserInterfacePreferences(Preferences preferences) {
        SwitchPreferenceCompat launcherPref = requirePreference(Preferences.KEY_LAUNCHER_ENABLED);
        launcherPref.setChecked(isLauncherEnabled());
        launcherPref.setOnPreferenceChangeListener(this);
        this.<SwitchPreferenceCompat>requirePreference(Preferences.KEY_CLEAR_PLAYLIST_CONFIRMATION).setChecked(preferences.isClearPlaylistConfirmation());
        fillEnumPreference(requirePreference(Preferences.KEY_TOP_BAR_SEARCH), Preferences.TopBarSearch.class, preferences.getTopBarSearch());

        fillEnumPreference(requirePreference(Preferences.KEY_CUSTOMIZE_HOME_MENU_MODE), Preferences.CustomizeHomeMenuMode.class, preferences.getCustomizeHomeMenuMode());
        fillEnumPreference(requirePreference(Preferences.KEY_CUSTOMIZE_SHORTCUT_MODE), Preferences.CustomizeShortcutsMode.class, preferences.getCustomizeShortcutsMode());

        fillEnumPreference(requirePreference(Preferences.KEY_ON_SWIPE_RIGHT_ACTION), PlayableItemAction.class, preferences.getSwipeRightAction());
        fillEnumPreference(requirePreference(Preferences.KEY_ON_SWIPE_LEFT_ACTION), PlayableItemAction.class, preferences.getSwipeLeftAction());
    }

    private boolean isLauncherEnabled() {
        ComponentName componentName = new ComponentName(requireContext(), "com.osmium.sound.companion.HomeLauncherActivity");
        int setting = requireContext().getPackageManager().getComponentEnabledSetting(componentName);
        return setting == PackageManager.COMPONENT_ENABLED_STATE_ENABLED;
    }

    private void updateLauncherMode(boolean enabled) {
        // TODO: HomeLauncherActivity not implemented in this companion app
        // ComponentName componentName = new ComponentName(requireContext(), "com.osmium.sound.companion.HomeLauncherActivity");
        // int setting = enabled ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED : PackageManager.COMPONENT_ENABLED_STATE_DISABLED;
        // requireContext().getPackageManager().setComponentEnabledSetting(componentName, setting, PackageManager.DONT_KILL_APP);
    }

    private <T extends Preference> T requirePreference(String key) {
        return findPreference(key);
    }

    private <E extends Enum<E> & EnumWithText> void fillEnumPreference(ListPreference listPreference, Class<E> actionTypes, E defaultValue) {
        fillEnumPreference(listPreference, actionTypes.getEnumConstants(), defaultValue);
    }

    private <E extends Enum<E> & EnumWithText> void fillEnumPreference(ListPreference listPreference, E[] actionTypes, E defaultValue) {
        String[] values = new String[actionTypes.length];
        String[] entries = new String[actionTypes.length];
        for (int i = 0; i < actionTypes.length; i++) {
            values[i] = actionTypes[i].name();
            entries[i] = actionTypes[i].getText(getActivity());
        }
        listPreference.setSummaryProvider(ListPreference.SimpleSummaryProvider.getInstance());
        listPreference.setEntryValues(values);
        listPreference.setEntries(entries);
        listPreference.setDefaultValue(defaultValue);
        if (listPreference.getValue() == null) {
            listPreference.setValue(defaultValue.name());
        }
        listPreference.setOnPreferenceChangeListener(this);
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        skinPollHandler.removeCallbacksAndMessages(null);
        getActivity().unbindService(serviceConnection);
    }

    private void updateFadeInSecondsSummary(int fadeInSeconds) {
        if (fadeInSeconds == 0) {
            fadeInPref.setSummary(R.string.disabled);
        } else {
            fadeInPref.setSummary(fadeInSeconds + " " + getResources()
                    .getQuantityString(R.plurals.seconds, fadeInSeconds));
        }
    }

    /**
     * A preference has been changed by the user, but has not yet been persisted.
     */
    @Override
    public boolean onPreferenceChange(Preference preference, Object newValue) {
        final String key = preference.getKey();
        Log.v(TAG, "preference change for: " + key);

        if (Preferences.KEY_FADE_IN_SECS.equals(key)) {
            updateFadeInSecondsSummary(Util.getInt(newValue.toString()));
        }

        // If the user has enabled Scrobbling but we don't think it will work
        // pop up a dialog with links to Google Play for apps to install.
        if (Preferences.KEY_SCROBBLE_ENABLED.equals(key)) {
            if (newValue.equals(true) && !Scrobble.canScrobble()) {
                new ScrobbleAppsDialog().show(getFragmentManager(), TAG);
                return false;
            }
        }

        // If the user has enabled action on call first check for permission
        if (Preferences.KEY_ACTION_ON_INCOMING_CALL.equals(key)) {
            requestCallStateLauncher.trySetAction(Preferences.IncomingCallAction.valueOf((String) newValue));
            return false;
        }

        if (Preferences.KEY_LAUNCHER_ENABLED.equals(key)) {
            if (newValue.equals(true)) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle(R.string.settings_launcher_title)
                        .setMessage(R.string.settings_launcher_explanation)
                        .setPositiveButton(R.string.settings_launcher_open_system_settings, (dialog, which) -> {
                            updateLauncherMode(true);
                            ((SwitchPreferenceCompat) preference).setChecked(true);
                            SharedPreferences.Editor editor = preference.getSharedPreferences().edit();
                            editor.putBoolean(Preferences.KEY_LAUNCHER_ENABLED, true);
                            editor.apply();

                            try {
                                Intent intent = new Intent(Settings.ACTION_HOME_SETTINGS);
                                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                                startActivity(intent);
                            } catch (ActivityNotFoundException e) {
                                try {
                                    Intent intent = new Intent(Settings.ACTION_SETTINGS);
                                    startActivity(intent);
                                } catch (Exception ex) {
                                    // ignore
                                }
                            }
                        })
                        .setNegativeButton(android.R.string.cancel, null)
                        .show();
                return false;
            }
        }

        return true;
    }

    private final CallStatePermissionLauncher requestCallStateLauncher = new CallStatePermissionLauncher(this);

    @Override
    public void requestCallStatePermission() {
        requestCallStateLauncher.requestCallStatePermission();
    }

    /**
     * A preference has been changed by the user and is going to be persisted.
     */
    @Override
    public void onSharedPreferenceChanged(SharedPreferences sharedPreferences, String key) {
        Log.v(TAG, "Preference changed: " + key);

        // The fragment may no longer be attached to its activity. If so, do nothing.
        if (!isAdded()) {
            return;
        }

        Preferences preferences = new Preferences(requireActivity(), sharedPreferences);

        if (key.equals(Preferences.KEY_DOWNLOAD_USE_SERVER_PATH) ||
                key.equals(Preferences.KEY_DOWNLOAD_ENABLED)
        ) {
            updateDownloadPreferences(preferences);
        }

        if (key.equals(Preferences.KEY_LAUNCHER_ENABLED)) {
            updateLauncherMode(sharedPreferences.getBoolean(key, false));
        }

        if (Preferences.KEY_ACTION_ON_INCOMING_CALL.equals(key)) {
            ListPreference incomingCallPref = requirePreference(Preferences.KEY_ACTION_ON_INCOMING_CALL);
            incomingCallPref.setValue(sharedPreferences.getString(Preferences.KEY_ACTION_ON_INCOMING_CALL, null));
            updateIncomingCallPreferences(preferences);
        }

        if (service != null) {
            service.preferenceChanged(preferences, key);
        } else {
            Log.v(TAG, "service is null!");
        }
    }

    public static class ScrobbleAppsDialog extends DialogFragment {
        @NonNull
        @Override
        public AlertDialog onCreateDialog(Bundle savedInstanceState) {
            final CharSequence[] apps = {
                    "Last.fm", "ScrobbleDroid", "SLS"
            };
            final CharSequence[] urls = {
                    "fm.last.android", "net.jjc1138.android.scrobbler",
                    "com.adam.aslfms"
            };

            final int[] icons = {
                    R.drawable.ic_launcher_lastfm,
                    R.drawable.ic_launcher_scrobbledroid, R.drawable.ic_launcher_sls
            };

            final View dialogView = getLayoutInflater().inflate(R.layout.scrobbler_choice_dialog, null);
            AlertDialog dialog = new MaterialAlertDialogBuilder(requireActivity())
                    .setView(dialogView)
                    .setTitle("Scrobbling applications")
                    .create();

            ListView appList = dialogView.findViewById(R.id.scrobble_apps);
            appList.setAdapter(new IconRowAdapter(getActivity(), apps, icons));

            final Context context = dialog.getContext();
            appList.setOnItemClickListener((parent, view, position, id1) -> {
                Intent intent = new Intent(Intent.ACTION_VIEW);
                intent.setData(Uri.parse("market://details?id=" + urls[position]));
                try {
                    startActivity(intent);
                } catch (ActivityNotFoundException e) {
                    Toast.makeText(context, R.string.settings_market_not_found,
                            Toast.LENGTH_SHORT).show();
                }
            });

            return dialog;
        }

    }
}
