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

package com.osmium.sound.companion.framework;

import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.LayoutRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.List;
import java.util.Map;

import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.SqueezerRepository;
import com.osmium.sound.companion.itemlist.IServiceItemListCallback;
import com.osmium.sound.companion.itemlist.dialog.ArtworkListLayout;
import com.osmium.sound.companion.model.Item;
import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.service.ISqueezeService;
import com.osmium.sound.companion.service.event.ActivePlayerChanged;
import com.osmium.sound.companion.service.event.HandshakeComplete;
import com.osmium.sound.companion.service.event.RefreshEvent;
import com.osmium.sound.companion.util.ImageFetcher;

/**
 * Fragment counterpart of {@link ItemListActivity}: it hosts the {@link RecyclerView}, the
 * {@link ItemAdapter} and the paging machinery, and is itself the {@link IServiceItemListCallback}
 * that receives the server's items. Unlike the activity it does not bind the service — it reads it
 * from the hosting kiosk shell ({@link BaseActivity}) and reacts to the shell's handshake /
 * active-player events, so the whole browse chain can live inside one shell with a persistent tab
 * bar and mini player (mirrors native-ui-qt's single-container Browser).
 *
 * @param <VH> View holder for items
 * @param <T>  the item type this fragment lists
 */
public abstract class ItemListFragment<VH extends ItemViewHolder<T>, T extends Item> extends Fragment
        implements IServiceItemListCallback<T> {

    private static final String TAG = ItemListFragment.class.getSimpleName();

    /** Number of items per page. */
    protected int mPageSize;

    private View loadingProgress;
    private RecyclerView listView;
    private ItemAdapter<VH, T> itemAdapter;

    /** Active player id the current list was ordered for, to avoid re-ordering on sticky replays. */
    private String currentPlayerId;

    @NonNull
    protected BaseActivity host() {
        return (BaseActivity) requireActivity();
    }

    @Nullable
    protected ISqueezeService getService() {
        return host().getService();
    }

    @NonNull
    protected ISqueezeService requireService() {
        return host().requireService();
    }

    protected SqueezerRepository repository() {
        return host().repository();
    }

    /**
     * The content layout. Must contain a {@link RecyclerView} with id {@code item_list} and a
     * {@code loading_label} progress indicator. Defaults to the browser layout (without the old
     * activity frame: no toolbar, no per-screen header, no duplicate mini player).
     */
    @LayoutRes
    protected int getContentView() {
        return R.layout.slim_browser_layout;
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        mPageSize = getResources().getInteger(R.integer.PageSize);
        return inflater.inflate(getContentView(), container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        loadingProgress = view.findViewById(R.id.loading_label);
        listView = view.findViewById(R.id.item_list);
        listView.setLayoutManager(new LinearLayoutManager(host()));
        listView.addOnScrollListener(new ScrollListener());
        listView.setAdapter(getItemAdapter());

        // repository() is backed by sticky LiveData, so subscribing here immediately replays the
        // current handshake / active-player state when the shell is already connected, which is
        // what kicks off the first page order; a later connect fires the same observers.
        repository().observe(getViewLifecycleOwner(), (HandshakeComplete event) -> onHandshakeComplete());
        repository().observe(getViewLifecycleOwner(), (ActivePlayerChanged event) -> setPlayer(event.player));
        repository().observe(getViewLifecycleOwner(), (RefreshEvent event) -> clearAndReOrderItems());
    }

    private void onHandshakeComplete() {
        ISqueezeService service = getService();
        Player activePlayer = (service != null ? service.getActivePlayer() : null);
        setPlayer(activePlayer);
        if (activePlayer != null) {
            maybeOrderVisiblePages(getListView());
        }
    }

    /** Re-orders page 0 when the active player actually changes (ignores sticky replays). */
    private void setPlayer(Player player) {
        String id = (player != null ? player.getId() : "");
        if (!id.equals(currentPlayerId)) {
            currentPlayerId = id;
            if (player != null) {
                clearAndReOrderItems();
            }
        }
    }

    @Override
    public void onPause() {
        super.onPause();
        // Items arriving after the fragment is paused are discarded; drop outstanding orders so
        // they are re-ordered on resume.
        getItemAdapter().cancelOrders();
    }

    protected void showLoading() {
        if (loadingProgress != null) loadingProgress.setVisibility(View.VISIBLE);
    }

    protected void showContent() {
        if (loadingProgress != null) loadingProgress.setVisibility(View.GONE);
    }

    /**
     * Starts an asynchronous fetch of items from the server, beginning at {@code start}. Called by
     * the adapter's paging through this fragment's {@link ItemAdapter.PageOrderer}.
     */
    protected abstract void orderPage(int start);

    protected abstract ItemAdapter<VH, T> createItemListAdapter();

    public ItemAdapter<VH, T> getItemAdapter() {
        if (itemAdapter == null) {
            itemAdapter = createItemListAdapter();
        }
        return itemAdapter;
    }

    public final RecyclerView getListView() {
        return listView;
    }

    public ArtworkListLayout getPreferredListLayout() {
        return HiFiMediaPlayer.getPreferences().getAlbumListLayout();
    }

    public void maybeOrderVisiblePages(RecyclerView listView) {
        LinearLayoutManager layoutManager = (LinearLayoutManager) listView.getLayoutManager();
        int firstVisibleItemPosition = layoutManager.findFirstVisibleItemPosition();
        if (firstVisibleItemPosition == RecyclerView.NO_POSITION) {
            getItemAdapter().maybeOrderPage(0);
        } else {
            int pos = (firstVisibleItemPosition / mPageSize) * mPageSize;
            int end = firstVisibleItemPosition + listView.getChildCount();
            while (pos < end) {
                getItemAdapter().maybeOrderPage(pos);
                pos += mPageSize;
            }
        }
    }

    /** Empties the tracked pages and orders page 0. */
    public void clearAndReOrderItems() {
        ISqueezeService service = getService();
        if (service != null && service.getActivePlayer() != null) {
            Log.i(TAG, "clearAndReOrderItems()");
            showLoading();
            getItemAdapter().clear();
            getItemAdapter().maybeOrderPage(0);
        }
    }

    protected void onItemsReceived(final int count, final int start, final List<T> items) {
        Log.d(TAG, "onItemsReceived(" + count + ", " + start + ", " + items.size() + ")");
        host().runOnUiThread(() -> {
            showContent();
            getItemAdapter().update(count, start, items);
        });
    }

    @Override
    public void onItemsReceived(int count, int start, Map<String, Object> parameters, List<T> items, Class<T> dataType) {
        onItemsReceived(count, start, items);
    }

    @Override
    public Object getClient() {
        return this;
    }

    /**
     * Tracks scrolling; when the list goes idle, new pages are fetched from the server.
     */
    private class ScrollListener extends RecyclerView.OnScrollListener {
        private int prevScrollState = RecyclerView.SCROLL_STATE_IDLE;

        @Override
        public void onScrollStateChanged(@NonNull RecyclerView listView, int scrollState) {
            if (scrollState == prevScrollState) return;
            prevScrollState = scrollState;

            boolean listScrolling = (scrollState != RecyclerView.SCROLL_STATE_IDLE);
            getItemAdapter().setListScrolling(listScrolling);
            if (!listScrolling) maybeOrderVisiblePages(listView);

            ImageFetcher.getInstance(host()).setPauseWork(listScrolling);
        }
    }
}
