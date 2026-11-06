package com.osmium.sound.companion;

import android.app.Activity;
import android.content.Context;

import androidx.annotation.DrawableRes;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;

import com.osmium.sound.companion.itemlist.AlarmsActivity;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The Settings tree shown as tiles, in the same grouping and order as the
 * kiosk's Settings (native-ui-qt/qml/SettingsTab.qml, {@code groups}) and the
 * names of its i18n keys (settings.groups.* / settings.sections.*).
 * <p>
 * A section either opens a screen of its own ({@link Section#launcher}) or a
 * short list of preferences ({@link Section#prefsKey}, a PreferenceScreen in
 * res/xml/preferences.xml). Sections of the device itself are marked
 * {@link Section#applianceOnly}: they are hidden on a plain Lyrion server,
 * where there is no appliance API behind them. Sections the companion app does
 * not offer (CD ripping, audio zones, Bluetooth speakers, the remote control
 * and the web remote) are left out on purpose.
 */
final class SettingsCatalog {

    private SettingsCatalog() {
    }

    /** Opens a section's own screen. */
    interface Launcher {
        void launch(Context context);
    }

    static final class Section {
        final String id;
        @DrawableRes
        final int icon;
        @StringRes
        final int title;
        final boolean applianceOnly;
        @Nullable
        final String prefsKey;
        @Nullable
        final Launcher launcher;

        private Section(String id, @DrawableRes int icon, @StringRes int title, boolean applianceOnly,
                        @Nullable String prefsKey, @Nullable Launcher launcher) {
            this.id = id;
            this.icon = icon;
            this.title = title;
            this.applianceOnly = applianceOnly;
            this.prefsKey = prefsKey;
            this.launcher = launcher;
        }

        boolean visible(boolean appliance) {
            return appliance || !applianceOnly;
        }
    }

    static final class Group {
        final String id;
        @DrawableRes
        final int icon;
        @StringRes
        final int title;
        final List<Section> sections;

        private Group(String id, @DrawableRes int icon, @StringRes int title, List<Section> sections) {
            this.id = id;
            this.icon = icon;
            this.title = title;
            this.sections = Collections.unmodifiableList(sections);
        }

        /** The sections listed for this device. */
        List<Section> visibleSections(boolean appliance) {
            List<Section> out = new ArrayList<>();
            for (Section s : sections) {
                if (s.visible(appliance)) out.add(s);
            }
            return out;
        }
    }

    private static Section leaf(String id, int icon, int title, boolean applianceOnly, String prefsKey) {
        return new Section(id, icon, title, applianceOnly, prefsKey, null);
    }

    private static Section screen(String id, int icon, int title, boolean applianceOnly, Launcher launcher) {
        return new Section(id, icon, title, applianceOnly, null, launcher);
    }

    static final List<Group> GROUPS = List.of(
            new Group("music", R.drawable.library_music, R.string.settings_group_music, List.of(
                    screen("sources", R.drawable.ic_archive, R.string.appliance_section_sources, true,
                            SourcesActivity::show),
                    leaf("playback", R.drawable.ic_action_play, R.string.appliance_section_playback, false,
                            SettingsFragment.SCREEN_PLAYBACK),
                    screen("multiroom", R.drawable.ic_speaker, R.string.settings_multiroom_title, true,
                            MultiroomActivity::show),
                    screen("alarm", R.drawable.alarm_clock, R.string.settings_tile_alarm, false,
                            ctx -> AlarmsActivity.show((Activity) ctx)),
                    leaf("download", R.drawable.ic_download, R.string.settings_category_download, false,
                            SettingsFragment.SCREEN_DOWNLOAD))),
            new Group("sound", R.drawable.ic_action_volume, R.string.settings_group_sound, List.of(
                    screen("audio", R.drawable.ic_action_volume, R.string.settings_tile_audio_output, true,
                            AudioOutputActivity::show))),
            new Group("look", R.drawable.ic_action_view_as_grid, R.string.settings_group_look, List.of(
                    leaf("language", R.drawable.ic_translate, R.string.settings_tile_language_screen, false,
                            SettingsFragment.SCREEN_DISPLAY),
                    screen("vuMeters", R.drawable.nowplaying, R.string.settings_tile_vu_meters, true,
                            VuMetersActivity::show),
                    screen("resolution", R.drawable.ic_action_view_as_grid, R.string.settings_tile_ui_resolution, true,
                            ResolutionActivity::show),
                    screen("refresh", R.drawable.ic_refresh, R.string.settings_ui_refresh_title, true,
                            RefreshRateActivity::show),
                    screen("displayMode", R.drawable.ic_action_view_as_grid, R.string.settings_tile_display_mode, true,
                            DisplayActivity::show),
                    screen("pointer", R.drawable.ic_settings, R.string.settings_tile_pointer, true,
                            PointerActivity::show),
                    leaf("nowplaying", R.drawable.nowplaying, R.string.settings_category_nowplaying_trackinfo, false,
                            SettingsFragment.SCREEN_NOW_PLAYING),
                    leaf("interface", R.drawable.ic_settings, R.string.settings_tile_interface, false,
                            SettingsFragment.SCREEN_INTERFACE))),
            new Group("control", R.drawable.ic_action_play, R.string.settings_group_control, List.of(
                    leaf("localPlayer", R.drawable.ic_menu_choose_player, R.string.pref_cat_local_player, false,
                            SettingsFragment.SCREEN_LOCAL_PLAYER),
                    leaf("thirdParty", R.drawable.apps, R.string.pref_cat_third_party, false,
                            SettingsFragment.SCREEN_THIRD_PARTY),
                    leaf("webRemoteIos", R.drawable.ic_qr_code_scanner, R.string.appliance_section_lyrplay, true,
                            SettingsFragment.SCREEN_LYRPLAY))),
            new Group("network", R.drawable.ic_dns, R.string.settings_group_network, List.of(
                    leaf("network", R.drawable.ic_dns, R.string.settings_tile_network, false,
                            SettingsFragment.SCREEN_CONNECTION),
                    screen("ssh", R.drawable.ic_settings, R.string.settings_tile_ssh, true,
                            ServicesActivity::show))),
            new Group("system", R.drawable.ic_info, R.string.settings_group_system, List.of(
                    leaf("timezone", R.drawable.ic_globe, R.string.appliance_section_timezone, true,
                            SettingsFragment.SCREEN_TIMEZONE),
                    screen("systemInfo", R.drawable.ic_info, R.string.settings_tile_system_info, true,
                            SystemInfoActivity::show),
                    screen("updates", R.drawable.ic_download, R.string.settings_updates_title, true,
                            UpdatesActivity::show),
                    screen("systemControls", R.drawable.ic_action_power_settings_new,
                            R.string.settings_tile_system_controls, true, SystemAdminActivity::show),
                    screen("backup", R.drawable.ic_save, R.string.settings_backup_title, true,
                            BackupRestoreActivity::show))));

    static Group group(String id) {
        for (Group g : GROUPS) {
            if (g.id.equals(id)) return g;
        }
        return null;
    }
}
