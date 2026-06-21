package com.hifi.mediaplayer.itemlist;

import android.app.Activity;
import android.content.Intent;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.AttrRes;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.List;

import com.hifi.mediaplayer.R;
import com.hifi.mediaplayer.framework.BaseActivity;
import com.hifi.mediaplayer.framework.ItemViewHolder;
import com.hifi.mediaplayer.model.Alarm;
import com.hifi.mediaplayer.model.AlarmPlaylist;

class AlarmPlaylistAdapter extends RecyclerView.Adapter<ItemViewHolder<AlarmPlaylist>> {
    private final BaseActivity activity;
    private final Alarm alarm;
    private List<AlarmPlaylist> playlists;

    public AlarmPlaylistAdapter(BaseActivity activity, Alarm alarm) {
        this.activity = activity;
        this.alarm = alarm;
    }

    @Override
    public int getItemCount() {
        return playlists.size();
    }

    @NonNull
    @Override
    public ItemViewHolder<AlarmPlaylist> onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new ViewHolder(activity, LayoutInflater.from(parent.getContext()).inflate(R.layout.dropdown_item, parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull ItemViewHolder<AlarmPlaylist> holder, int position) {
        holder.bindView(playlists.get(position));
    }

    public void setItems(List<AlarmPlaylist> playlists) {
        this.playlists = playlists;
        notifyDataSetChanged();
    }

    private class ViewHolder extends ItemViewHolder<AlarmPlaylist> {

        public ViewHolder(@NonNull BaseActivity activity, @NonNull View view) {
            super(activity, view);
        }

        @Override
        public void bindView(AlarmPlaylist item) {
            super.bindView(item);
            ((TextView) itemView).setText(item.getName());
            @AttrRes int background = (item.getId().equals(alarm.getPlayListId())) ? R.attr.currentTrackBackground : R.attr.selectableItemBackground;
            itemView.setBackgroundResource(getActivity().getAttributeValue(background));
            itemView.setOnClickListener(v -> {
                Intent intent = new Intent().putExtra(AlarmPlaylistActivity.ALARM_PLAYLIST, item);
                getActivity().setResult(Activity.RESULT_OK, intent);
                getActivity().finish();
            });
        }
    }
}
