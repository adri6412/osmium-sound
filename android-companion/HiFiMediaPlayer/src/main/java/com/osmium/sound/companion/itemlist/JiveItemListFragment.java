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
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextUtils;
import android.util.Base64;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import androidx.webkit.WebSettingsCompat;
import androidx.webkit.WebViewFeature;

import com.google.android.material.textfield.TextInputLayout;
import com.qtalk.recyclerviewfastscroller.RecyclerViewFastScroller;

import java.util.List;
import java.util.Map;

import com.osmium.sound.companion.NowPlayingActivity;
import com.osmium.sound.companion.R;
import com.osmium.sound.companion.Util;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.framework.ItemAdapter;
import com.osmium.sound.companion.framework.ItemListFragment;
import com.osmium.sound.companion.framework.ItemViewHolder;
import com.osmium.sound.companion.itemlist.dialog.ArtworkListLayout;
import com.osmium.sound.companion.kiosk.MainActivity;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;
import com.osmium.sound.companion.model.Window;
import com.osmium.sound.companion.util.AfterTextChangedLister;
import com.osmium.sound.companion.widget.GridAutofitLayoutManager;

/**
 * The browse list rendered inside the kiosk shell: the fragment counterpart of
 * {@link JiveItemListActivity}. It carries the same {@code parent}/{@code action} (through its
 * arguments instead of an intent) and the same {@code orderPage}/{@code onItemsReceived}/input
 * machinery, but with no toolbar, no per-screen header (the shell's breadcrumb takes its place) and
 * no duplicate mini player. Drill-down pushes another instance of this fragment on the shell's back
 * stack (see {@link JiveItemListActivity#show}).
 */
public class JiveItemListFragment extends ItemListFragment<ItemViewHolder<JiveItem>, JiveItem> {

    private JiveItem parent;
    private Action action;
    private final Window window = new Window();

    private RecyclerViewFastScroller fastScroller;

    public static JiveItemListFragment newInstance(JiveItem parent, @Nullable Action action) {
        JiveItemListFragment fragment = new JiveItemListFragment();
        Bundle args = new Bundle();
        args.putParcelable(JiveItem.class.getName(), parent);
        args.putParcelable(Action.class.getName(), action);
        fragment.setArguments(args);
        return fragment;
    }

    /** The title the shell shows for this level in the breadcrumb. */
    public CharSequence getBrowseTitle() {
        if (parent != null && !TextUtils.isEmpty(parent.getName())) {
            return parent.getName();
        }
        return "";
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Bundle args = getArguments();
        if (args != null) {
            parent = args.getParcelable(JiveItem.class.getName());
            action = args.getParcelable(Action.class.getName());
        }
    }

    private boolean isPlaylist() {
        return parent != null && "playlist".equals(parent.getType());
    }

    private boolean hasInputField() {
        return parent != null && parent.hasInputField();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        fastScroller = view.findViewById(R.id.fastscroller);

        updateHeader(null);
        setupInputField(view);
    }

    @Override
    protected ItemAdapter<ItemViewHolder<JiveItem>, JiveItem> createItemListAdapter() {
        // Driven by this fragment (orderer + callback) but navigated through the shell (host).
        JiveItemAdapter adapter = new JiveItemAdapter(host(), this::orderPage);
        adapter.setParent(parent);
        return adapter;
    }

    @Override
    protected void orderPage(int start) {
        if (parent != null) {
            if (parent.hasSubItems()) {
                onItemsReceived(parent.subItems.size(), 0, parent.subItems);
            } else if (action == null || (parent.hasInput() && !parent.isInputReady())) {
                showContent();
            } else {
                requireService().pluginItems(start, parent, action, this);
            }
        }
    }

    @Override
    public void onItemsReceived(int count, int start, Map<String, Object> parameters, List<JiveItem> items, Class<JiveItem> dataType) {
        if (parameters.containsKey("goNow")) {
            Action.NextWindow nextWindow = Action.NextWindow.fromString(Util.getString(parameters, "goNow"));
            BaseActivity host = host();
            switch (nextWindow.nextWindow) {
                case nowPlaying -> NowPlayingActivity.show(host);
                case playlist -> CurrentPlaylistActivity.show(host);
                case home -> MainActivity.show(host);
            }
            popSelf();
            return;
        }

        final Window win = JiveItem.extractWindow(Util.getRecord(parameters, "window"), null);
        if (win != null) {
            // override server based icon_list style for playlist results
            if (win.windowStyle == Window.WindowStyle.ICON_LIST && isPlaylist()) {
                win.windowStyle = Window.WindowStyle.PLAY_LIST;
            }
            host().runOnUiThread(() -> updateHeader(win));
        }

        if (parameters.containsKey("networkerror")) {
            String errorMsg = Util.getString(parameters, "networkerror");
            host().runOnUiThread(() -> host().showDisplayMessage(errorMsg));
        }

        super.onItemsReceived(count, start, parameters, items, dataType);

        boolean hasTextKey = items.stream().anyMatch(item -> !TextUtils.isEmpty(item.textkey));
        if (fastScroller != null) {
            host().runOnUiThread(() -> fastScroller.popupTextView.setVisibility(hasTextKey ? View.VISIBLE : View.GONE));
        }
    }

    private void popSelf() {
        if (isAdded()) {
            host().getSupportFragmentManager().popBackStack();
        }
    }

    // --- Header (sub-header / html content) + list style --------------------------------------

    private void updateHeader(Window win) {
        if (win == null && parent != null) win = parent.window;

        if (win != null) {
            updateWindowStyle(win.windowStyle);
        } else if (isPlaylist()) {
            updateWindowStyle(Window.WindowStyle.PLAY_LIST);
        } else {
            updateWindowStyle(Window.WindowStyle.TEXT_ONLY);
        }

        View root = getView();
        if (root == null || hasInputField()) return;

        root.findViewById(R.id.sub_header_container).setVisibility(View.GONE);
        root.findViewById(R.id.content).setVisibility(View.GONE);
        if (win != null && !TextUtils.isEmpty(win.html)) {
            WebView header = root.findViewById(R.id.content);
            if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
                WebSettingsCompat.setAlgorithmicDarkeningAllowed(header.getSettings(), true);
            }
            String encoded = Base64.encodeToString(win.html.getBytes(), Base64.NO_PADDING);
            header.loadData(encoded, "text/html", "base64");
            header.setVisibility(View.VISIBLE);
        } else if (win != null && !TextUtils.isEmpty(win.textarea)) {
            TextView header = root.findViewById(R.id.sub_header);
            header.setText(win.textarea);
            root.findViewById(R.id.sub_header_container).setVisibility(View.VISIBLE);
        }
    }

    private void updateWindowStyle(Window.WindowStyle windowStyle) {
        window.windowStyle = windowStyle;
        ItemAdapter<ItemViewHolder<JiveItem>, JiveItem> adapter = getItemAdapter();
        if (windowStyle != null && adapter instanceof JiveItemAdapter jiveItemAdapter) {
            jiveItemAdapter.setWindowStyle(getPreferredListLayout(), windowStyle);
        }
        setupListView(getListView(), getListLayout());
        adapter.notifyItemRangeChanged(0, adapter.getItemCount());
    }

    public ArtworkListLayout getListLayout() {
        return JiveItemView.listLayout(getPreferredListLayout(), window.windowStyle);
    }

    private void setupListView(RecyclerView list, ArtworkListLayout listLayout) {
        if (list == null) return;
        RecyclerView.LayoutManager layoutManager = list.getLayoutManager();
        if (listLayout == ArtworkListLayout.grid && !(layoutManager instanceof GridLayoutManager)) {
            list.setLayoutManager(new GridAutofitLayoutManager(host(), R.dimen.grid_column_width));
        }
        if ((listLayout == ArtworkListLayout.list || listLayout == ArtworkListLayout.grouped) && (layoutManager instanceof GridLayoutManager)) {
            list.setLayoutManager(new LinearLayoutManager(host()));
        }
    }

    // --- Input field (search / text / email / password) --------------------------------------

    private void clearAndReOrderItems(String inputString) {
        if (getService() != null && !TextUtils.isEmpty(inputString)) {
            parent.inputValue = inputString;
            clearAndReOrderItems();
        }
    }

    private void setupInputField(@NonNull View root) {
        View inputLayoutView = root.findViewById(R.id.plugin_input_til);
        inputLayoutView.setVisibility(hasInputField() ? View.VISIBLE : View.GONE);
        if (!hasInputField()) return;

        final EditText inputText = root.findViewById(R.id.plugin_input);
        TextInputLayout inputTextLayout = root.findViewById(R.id.plugin_input_til);
        inputTextLayout.setHint(TextUtils.isEmpty(parent.input.title) ? window.text : parent.input.title);
        inputText.post(() -> {
            inputText.requestFocus();
            InputMethodManager imm = (InputMethodManager) host().getSystemService(android.content.Context.INPUT_METHOD_SERVICE);
            imm.showSoftInput(inputText, InputMethodManager.SHOW_IMPLICIT);
        });
        inputText.setText(parent.input.initialText);
        parent.inputValue = parent.input.initialText;

        inputText.setOnKeyListener((v, keyCode, event) -> {
            if ((event.getAction() == KeyEvent.ACTION_DOWN) && (keyCode == KeyEvent.KEYCODE_ENTER)) {
                clearAndReOrderItems(inputText.getText().toString());
                return true;
            }
            return false;
        });

        if (action != null && action.getInputType() == Action.InputType.SEARCH) {
            Handler handler = new Handler(Looper.getMainLooper());
            final Runnable[] job = {null};
            inputText.addTextChangedListener(new AfterTextChangedLister() {
                @Override
                public void afterTextChanged(Editable s) {
                    if (job[0] != null) handler.removeCallbacks(job[0]);
                    if (TextUtils.isEmpty(s)) {
                        getItemAdapter().clear();
                    } else {
                        job[0] = () -> clearAndReOrderItems(inputText.getText().toString());
                        handler.postDelayed(job[0], 1000);
                    }
                }
            });
            inputTextLayout.setEndIconMode(TextInputLayout.END_ICON_CLEAR_TEXT);
        } else {
            int inputType = EditorInfo.TYPE_CLASS_TEXT | switch (action != null ? action.getInputType() : Action.InputType.TEXT) {
                case EMAIL -> EditorInfo.TYPE_TEXT_VARIATION_EMAIL_ADDRESS;
                case PASSWORD -> EditorInfo.TYPE_TEXT_VARIATION_PASSWORD;
                default -> 0;
            };
            inputText.setInputType(inputType);
            inputTextLayout.setEndIconDrawable(R.drawable.keyboard_return);
            inputTextLayout.setEndIconOnClickListener(v -> clearAndReOrderItems(inputText.getText().toString()));
        }
    }
}
