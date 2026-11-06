/*
 * Copyright (c) 2009 Google Inc.  All Rights Reserved.
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

package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;
import androidx.preference.PreferenceFragmentCompat;

import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Settings, as a grid of tiles: the macro groups first, then the sections of
 * the chosen group (see {@link SettingsCatalog}). A section that is a list of
 * preferences opens a {@link SettingsFragment} leaf; one that is a screen of
 * its own is launched directly.
 */
public class SettingsActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.settings);
        setSupportActionBar(findViewById(R.id.toolbar));
        ViewUtilities.setInsetsListener(findViewById(R.id.toolbar), true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.settings_container), false, true, false);

        if (savedInstanceState == null) {
            getSupportFragmentManager()
                    .beginTransaction()
                    .replace(R.id.settings_container, SettingsTilesFragment.newInstance(null), "settings-groups")
                    .commit();
        }

        getSupportFragmentManager().addOnBackStackChangedListener(() -> {
            if (getSupportFragmentManager().getBackStackEntryCount() == 0) {
                setTitle(R.string.activity_settings_name);
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
        mThemeManager.onResume(this);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            if (getSupportFragmentManager().getBackStackEntryCount() > 0) {
                getSupportFragmentManager().popBackStack();
            } else {
                finish();
            }
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    /** Opens a macro group: its sections as tiles. */
    void openGroup(SettingsCatalog.Group group) {
        navigate(SettingsTilesFragment.newInstance(group.id), "group:" + group.id, getString(group.title));
    }

    /** Opens a section: its own screen, or its list of preferences. */
    void openSection(SettingsCatalog.Section section) {
        if (section.launcher != null) {
            section.launcher.launch(this);
            return;
        }
        SettingsFragment fragment = new SettingsFragment();
        Bundle args = new Bundle();
        args.putString(PreferenceFragmentCompat.ARG_PREFERENCE_ROOT, section.prefsKey);
        fragment.setArguments(args);
        navigate(fragment, section.prefsKey, getString(section.title));
    }

    private void navigate(Fragment fragment, String tag, String title) {
        getSupportFragmentManager()
                .beginTransaction()
                .replace(R.id.settings_container, fragment, tag)
                .addToBackStack(tag)
                .commit();
        setTitle(title);
    }

    public static void show(Context context) {
        final Intent intent = new Intent(context, SettingsActivity.class);
        context.startActivity(intent);
    }
}
