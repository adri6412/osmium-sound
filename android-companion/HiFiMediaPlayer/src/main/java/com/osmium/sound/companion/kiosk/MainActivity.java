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

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.tabs.TabLayout;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.SettingsActivity;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.itemlist.CurrentPlaylistActivity;
import com.osmium.sound.companion.itemlist.HomeActivity;
import com.osmium.sound.companion.itemlist.JiveItemListFragment;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;
import com.osmium.sound.companion.service.ISqueezeService;

/**
 * The app's kiosk-style shell: a tab bar (Music / Radio / Apps / Settings), the active section in
 * the middle, and a persistent mini player at the bottom (the {@code now_playing_fragment} in
 * {@link R.layout#activity_main_kiosk}, which expands into the full Now Playing on tap). It mirrors
 * native-ui-qt's MainScreen + Browser + MiniPlayer.
 *
 * <p>The Music tab is the kiosk home grid ({@link HomeTilesFragment}); drilling into a category
 * pushes a {@link JiveItemListFragment} into the same container ({@link #pushBrowse}), with a
 * breadcrumb strip replacing the old per-level toolbars. Radio and Apps still open the server-driven
 * menu ({@link HomeActivity}) for now; Settings opens the existing settings screens.
 */
public class MainActivity extends BaseActivity implements JiveItemNavigator {

    private static final int TAB_MUSIC = 0;
    private static final int TAB_RADIO = 1;
    private static final int TAB_APPS = 2;
    private static final int TAB_SETTINGS = 3;

    private TabLayout tabs;
    private HorizontalScrollView breadcrumbScroll;
    private LinearLayout breadcrumb;
    /** Guards programmatic tab selection so it does not re-trigger a launch. */
    private boolean switchingTab;

    /**
     * Brings the kiosk shell to the front, reusing the running instance. This is the app's home: the
     * connect flow and every "go home" action land here, not on the old server-menu
     * {@link HomeActivity}.
     */
    public static void show(Context context) {
        Intent intent = new Intent(context, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (!(context instanceof Activity)) {
            intent = intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        }
        context.startActivity(intent);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main_kiosk);

        breadcrumbScroll = findViewById(R.id.kiosk_breadcrumb_scroll);
        breadcrumb = findViewById(R.id.kiosk_breadcrumb);

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

        getSupportFragmentManager().addOnBackStackChangedListener(this::rebuildBreadcrumb);

        if (savedInstanceState == null) showMusic();
        rebuildBreadcrumb();
    }

    @Override
    public void onResume() {
        super.onResume();
        // Coming back from a launched screen (Radio / Apps / Settings): the shell always rests on
        // the Music home.
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

    /** Resets the Music tab to its home grid, dropping any pushed browse levels. */
    private void showMusic() {
        FragmentManager fm = getSupportFragmentManager();
        if (fm.getBackStackEntryCount() > 0) {
            fm.popBackStack(fm.getBackStackEntryAt(0).getId(), FragmentManager.POP_BACK_STACK_INCLUSIVE);
        }
        fm.beginTransaction()
                .replace(R.id.kiosk_content, new HomeTilesFragment())
                .commit();
    }

    private void selectMusicTab() {
        switchingTab = true;
        TabLayout.Tab music = tabs.getTabAt(TAB_MUSIC);
        if (music != null) music.select();
        switchingTab = false;
    }

    // --- JiveItemNavigator -----------------------------------------------------------------------

    @Override
    public void pushBrowse(JiveItem parent, @Nullable Action action) {
        JiveItemListFragment fragment = JiveItemListFragment.newInstance(parent, action);
        String title = (parent != null && parent.getName() != null) ? parent.getName() : "";
        getSupportFragmentManager().beginTransaction()
                .replace(R.id.kiosk_content, fragment)
                .addToBackStack(title)
                .commit();
    }

    // --- Breadcrumb ------------------------------------------------------------------------------

    private void rebuildBreadcrumb() {
        if (breadcrumb == null) return;
        FragmentManager fm = getSupportFragmentManager();
        int levels = fm.getBackStackEntryCount();
        breadcrumb.removeAllViews();

        if (levels == 0) {
            breadcrumbScroll.setVisibility(View.GONE);
            return;
        }
        breadcrumbScroll.setVisibility(View.VISIBLE);

        // The home grid is always the root crumb; tapping it drops every pushed browse level.
        addCrumb(getString(R.string.kiosk_tab_music), false, v -> showMusic());
        for (int i = 0; i < levels; i++) {
            final FragmentManager.BackStackEntry entry = fm.getBackStackEntryAt(i);
            addSeparator();
            addCrumb(String.valueOf(entry.getName()), i == levels - 1,
                    v -> fm.popBackStack(entry.getId(), 0));
        }
        breadcrumbScroll.post(() -> breadcrumbScroll.fullScroll(View.FOCUS_RIGHT));
    }

    private void addCrumb(CharSequence label, boolean current, View.OnClickListener onClick) {
        TextView view = new TextView(this);
        view.setText(label);
        view.setMaxLines(1);
        view.setTextColor(getColor(current ? R.color.osmium_gold : R.color.osmium_silver));
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        view.setPadding(dp(4), dp(2), dp(4), dp(2));
        view.setGravity(Gravity.CENTER_VERTICAL);
        if (!current) {
            TypedValue outValue = new TypedValue();
            getTheme().resolveAttribute(android.R.attr.selectableItemBackground, outValue, true);
            view.setBackgroundResource(outValue.resourceId);
            view.setOnClickListener(onClick);
        }
        breadcrumb.addView(view);
    }

    private void addSeparator() {
        TextView sep = new TextView(this);
        sep.setText("›");
        sep.setTextColor(getColor(R.color.osmium_silver));
        sep.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        sep.setPadding(dp(2), dp(2), dp(2), dp(2));
        breadcrumb.addView(sep);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    // --- Navigation after an action (nextWindow), ported from JiveItemListActivity ---------------

    @Override
    public void action(JiveItem item, Action action, int alreadyPopped) {
        if (getService() == null) return;
        if (action != null) getService().action(item, action);

        Action.JsonAction jAction = (action != null && action.action != null) ? action.action : null;
        Action.NextWindow nextWindow = (jAction != null ? jAction.nextWindow : item.nextWindow);
        navigateNextWindow(nextWindow, alreadyPopped);
    }

    @Override
    public void action(JiveItem item, Action.JsonAction action, int alreadyPopped) {
        if (getService() == null) return;
        getService().action(action);
        navigateNextWindow(action.nextWindow, alreadyPopped);
    }

    private void navigateNextWindow(Action.NextWindow nextWindow, int alreadyPopped) {
        while (alreadyPopped > 0 && nextWindow != null) {
            nextWindow = popNextWindow(nextWindow);
            alreadyPopped--;
        }
        if (nextWindow == null) return;

        FragmentManager fm = getSupportFragmentManager();
        switch (nextWindow.nextWindow) {
            case nowPlaying -> {
                // Always available via the mini player; nothing to navigate.
            }
            case playlist -> CurrentPlaylistActivity.show(this);
            case home -> showMusic();
            case parent, parentNoRefresh, windowId -> fm.popBackStack();
            case grandparent -> {
                fm.popBackStack();
                fm.popBackStack();
            }
            case refresh, refreshOrigin -> refreshCurrentBrowse();
        }
    }

    private Action.NextWindow popNextWindow(Action.NextWindow nextWindow) {
        return switch (nextWindow.nextWindow) {
            case parent, parentNoRefresh -> null;
            case grandparent -> new Action.NextWindow(Action.NextWindowEnum.parentNoRefresh);
            case refreshOrigin -> new Action.NextWindow(Action.NextWindowEnum.refresh);
            default -> nextWindow;
        };
    }

    private void refreshCurrentBrowse() {
        Fragment current = getSupportFragmentManager().findFragmentById(R.id.kiosk_content);
        if (current instanceof JiveItemListFragment browse) {
            browse.clearAndReOrderItems();
        }
    }

    @Override
    protected void onServiceConnected(@NonNull ISqueezeService service) {
        super.onServiceConnected(service);
    }
}
