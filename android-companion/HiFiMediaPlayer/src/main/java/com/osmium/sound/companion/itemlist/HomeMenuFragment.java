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

package com.osmium.sound.companion.itemlist;

import android.os.Bundle;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.framework.ItemAdapter;
import com.osmium.sound.companion.framework.ItemListFragment;
import com.osmium.sound.companion.framework.ItemViewHolder;
import com.osmium.sound.companion.itemlist.dialog.ArtworkListLayout;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;
import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.model.Window;
import com.osmium.sound.companion.service.event.HomeMenuEvent;
import com.osmium.sound.companion.widget.GridAutofitLayoutManager;

/**
 * A server-driven home menu level rendered inside the kiosk shell: the fragment counterpart of
 * {@link HomeMenuActivity}. Its children come from the sticky {@link HomeMenuEvent} (a flat list
 * filtered by {@code node}), so it does not page from the server. Drill-down into a node pushes
 * another instance on the shell's back stack (see {@code JiveItemNavigator#pushHomeMenu}).
 */
public class HomeMenuFragment extends ItemListFragment<ItemViewHolder<JiveItem>, JiveItem> {

    private static final String ARG_NODE = "homeMenuNode";

    private JiveItem parent;

    public static HomeMenuFragment newInstance(JiveItem node) {
        HomeMenuFragment fragment = new HomeMenuFragment();
        Bundle args = new Bundle();
        args.putParcelable(ARG_NODE, node);
        fragment.setArguments(args);
        return fragment;
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Bundle args = getArguments();
        if (args != null) {
            parent = args.getParcelable(ARG_NODE);
        }
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        applyWindowStyle();
        repository().observe(getViewLifecycleOwner(), this::onHomeMenuEvent);
    }

    @Override
    protected ItemAdapter<ItemViewHolder<JiveItem>, JiveItem> createItemListAdapter() {
        // Rows navigate through the shell (host); the menu itself is driven by HomeMenuEvent.
        return new JiveItemAdapter(host(), this::orderPage);
    }

    @Override
    protected void orderPage(int start) {
        // Do nothing: the menu comes from the sticky HomeMenuEvent.
    }

    @Override
    public void clearAndReOrderItems() {
        // Do nothing: the menu comes from the sticky HomeMenuEvent.
    }

    @Override
    public void maybeOrderVisiblePages(RecyclerView listView) {
        // Do nothing: the menu comes from the sticky HomeMenuEvent.
    }

    @Override
    public ArtworkListLayout getPreferredListLayout() {
        return HiFiMediaPlayer.getPreferences().getHomeMenuLayout();
    }

    private void onHomeMenuEvent(HomeMenuEvent event) {
        if (parent == null || !isAdded()) return;
        getItemAdapter().clear();
        List<JiveItem> menu = getMenuNode(parent.getId(), event.menuItems);
        onItemsReceived(menu.size(), 0, menu);
    }

    /** Returns the menu items of {@code node} that are visible for the active player, by weight then name. */
    private List<JiveItem> getMenuNode(String node, List<JiveItem> homeMenu) {
        ArrayList<JiveItem> menu = new ArrayList<>();
        for (JiveItem item : homeMenu) {
            if (node.equals(item.getNode()) && (item.goAction == null || forActivePlayer(item.goAction))) {
                menu.add(item);
            }
        }
        Collections.sort(menu, (o1, o2) -> {
            if (o1.getWeight() == o2.getWeight()) {
                return o1.getName().compareTo(o2.getName());
            }
            return o1.getWeight() - o2.getWeight();
        });
        return menu;
    }

    /** Same rule as {@code JiveItemListActivity#forActivePlayer}. */
    private boolean forActivePlayer(Action action) {
        Player activePlayer = requireService().getActivePlayer();
        String playerId = (activePlayer != null ? activePlayer.getId() : null);
        return !action.isPlayerSpecific() || Arrays.asList(action.action.players).contains(playerId);
    }

    /** Home menu rows use the home-menu window style and the preferred home-menu layout. */
    private void applyWindowStyle() {
        ItemAdapter<ItemViewHolder<JiveItem>, JiveItem> adapter = getItemAdapter();
        if (adapter instanceof JiveItemAdapter jiveItemAdapter) {
            jiveItemAdapter.setWindowStyle(getPreferredListLayout(), Window.WindowStyle.HOME_MENU);
        }
        RecyclerView list = getListView();
        if (list == null) return;
        ArtworkListLayout listLayout = JiveItemView.listLayout(getPreferredListLayout(), Window.WindowStyle.HOME_MENU);
        RecyclerView.LayoutManager layoutManager = list.getLayoutManager();
        if (listLayout == ArtworkListLayout.grid && !(layoutManager instanceof GridLayoutManager)) {
            list.setLayoutManager(new GridAutofitLayoutManager(host(), R.dimen.grid_column_width));
        } else if ((listLayout == ArtworkListLayout.list || listLayout == ArtworkListLayout.grouped)
                && layoutManager instanceof GridLayoutManager) {
            list.setLayoutManager(new LinearLayoutManager(host()));
        }
        adapter.notifyItemRangeChanged(0, adapter.getItemCount());
    }
}
