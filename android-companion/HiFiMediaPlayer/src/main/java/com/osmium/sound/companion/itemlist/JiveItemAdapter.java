package com.osmium.sound.companion.itemlist;

import android.view.View;

import androidx.annotation.NonNull;

import com.qtalk.recyclerviewfastscroller.RecyclerViewFastScroller;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.framework.ItemAdapter;
import com.osmium.sound.companion.framework.ItemViewHolder;
import com.osmium.sound.companion.itemlist.dialog.ArtworkListLayout;
import com.osmium.sound.companion.model.JiveItem;
import com.osmium.sound.companion.model.Window;

class JiveItemAdapter extends ItemAdapter<ItemViewHolder<JiveItem>, JiveItem> implements RecyclerViewFastScroller.OnPopupTextUpdate {
    private Window.WindowStyle windowStyle = Window.WindowStyle.TEXT_ONLY;
    protected ArtworkListLayout listLayout = ArtworkListLayout.list;

    /**
     * Per-list state that used to live on {@link JiveItemListActivity}. Keeping it on the adapter lets
     * the row views (which only hold a {@link BaseActivity}) stay agnostic of their host, so the same
     * adapter and rows can be driven either by an activity or by a fragment in the kiosk shell.
     */
    private JiveItem parent;
    private int selectedIndex;

    public JiveItemAdapter(JiveItemListActivity activity) {
        super(activity);
    }

    public JiveItem getParent() {
        return parent;
    }

    public void setParent(JiveItem parent) {
        this.parent = parent;
    }

    public int getSelectedIndex() {
        return selectedIndex;
    }

    public void setSelectedIndex(int selectedIndex) {
        this.selectedIndex = selectedIndex;
    }

    public void setWindowStyle(ArtworkListLayout preferredListLayout, Window.WindowStyle windowStyle) {
        this.windowStyle = windowStyle;
        listLayout = JiveItemView.listLayout(preferredListLayout, windowStyle);
    }

    @Override
    public ItemViewHolder<JiveItem> createViewHolder(View view, int viewType) {
        if (viewType == R.layout.grid_item_pending || viewType == R.layout.list_item_pending) {
            return new JiveItemViewPending(getActivity(), view, windowStyle != Window.WindowStyle.TEXT_ONLY);
        } else if (viewType == R.layout.slider_item) {
            return new SliderView(getActivity(), view);
        } else {
            return new JiveItemView(getActivity(), windowStyle, listLayout, view);
        }
    }

    @Override
    protected int getItemViewType(JiveItem item) {
        if (item == null) {
            return (listLayout == ArtworkListLayout.grid) ? R.layout.grid_item_pending : R.layout.list_item_pending;
        }
        return item.hasSlider()
                ? R.layout.slider_item
                : (listLayout == ArtworkListLayout.grid) ? R.layout.grid_item : R.layout.list_item;
    }

    public ArtworkListLayout getListLayout() {
        return listLayout;
    }

    @NonNull
    @Override
    public CharSequence onChange(int position) {
        JiveItem item = getItem(position);
        return (item != null ? item.textkey : "");
    }

    @Override
    public int getActiveCount() {
        int n = 0;
        for (int p = 0; p < getItemCount(); p++) {
            JiveItem item = item(p);
            if (item == null || item.isSelectable()) n++;
        }
        return n;
    }
}
