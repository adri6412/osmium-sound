/*
 * Copyright (c) 2026 Osmium Sound
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.osmium.sound.companion.kiosk;

import android.content.Intent;
import android.os.Bundle;

import androidx.annotation.NonNull;

import com.google.android.material.tabs.TabLayout;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.SettingsActivity;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.itemlist.HomeActivity;
import com.osmium.sound.companion.service.ISqueezeService;

/**
 * The app's kiosk-style shell: a tab bar (Music / Radio / Apps / Settings), the
 * active section in the middle, and a persistent mini player at the bottom (the
 * {@code now_playing_fragment} in {@link R.layout#activity_main_kiosk}, which
 * expands into the full Now Playing on tap). It mirrors native-ui-qt's
 * MainScreen + Browser + MiniPlayer.
 *
 * <p>The Music tab is the kiosk home grid ({@link HomeTilesFragment}). Radio and
 * Apps still open the server-driven menu ({@link HomeActivity}) for now; the next
 * milestone renders them inside this container. Settings opens the existing
 * settings screens.
 */
public class MainActivity extends BaseActivity {

    private static final int TAB_MUSIC = 0;
    private static final int TAB_RADIO = 1;
    private static final int TAB_APPS = 2;
    private static final int TAB_SETTINGS = 3;

    private TabLayout tabs;
    /** Guards programmatic tab selection so it does not re-trigger a launch. */
    private boolean switchingTab;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main_kiosk);

        tabs = findViewById(R.id.kiosk_tabs);
        tabs.addTab(tabs.newTab().setIcon(R.drawable.library_music).setText(R.string.kiosk_tab_music));
        tabs.addTab(tabs.newTab().setIcon(R.drawable.internet_radio).setText(R.string.kiosk_tab_radio));
        tabs.addTab(tabs.newTab().setIcon(R.drawable.apps).setText(R.string.kiosk_tab_apps));
        tabs.addTab(tabs.newTab().setIcon(R.drawable.settings).setText(R.string.kiosk_tab_settings));

        tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                if (switchingTab) return;
                onTab(tab.getPosition());
            }

            @Override
            public void onTabUnselected(TabLayout.Tab tab) {
            }

            @Override
            public void onTabReselected(TabLayout.Tab tab) {
                if (!switchingTab && tab.getPosition() == TAB_MUSIC) showMusic();
            }
        });

        if (savedInstanceState == null) showMusic();
    }

    @Override
    public void onResume() {
        super.onResume();
        // Coming back from a launched screen (Radio / Apps / Settings): the shell
        // always rests on the Music home.
        if (tabs != null && tabs.getSelectedTabPosition() != TAB_MUSIC) {
            selectMusicTab();
            showMusic();
        }
    }

    private void onTab(int position) {
        switch (position) {
            case TAB_MUSIC -> showMusic();
            case TAB_RADIO, TAB_APPS -> HomeActivity.show(this);
            case TAB_SETTINGS -> startActivity(new Intent(this, SettingsActivity.class));
        }
    }

    private void showMusic() {
        getSupportFragmentManager().beginTransaction()
                .replace(R.id.kiosk_content, new HomeTilesFragment())
                .commit();
    }

    private void selectMusicTab() {
        switchingTab = true;
        TabLayout.Tab music = tabs.getTabAt(TAB_MUSIC);
        if (music != null) music.select();
        switchingTab = false;
    }

    @Override
    protected void onServiceConnected(@NonNull ISqueezeService service) {
        super.onServiceConnected(service);
    }
}
