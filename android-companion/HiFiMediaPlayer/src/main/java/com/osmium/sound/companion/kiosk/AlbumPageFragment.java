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

import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.widget.PopupMenu;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.button.MaterialButton;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.Util;
import com.osmium.sound.companion.framework.BaseActivity;
import com.osmium.sound.companion.itemlist.IServiceItemListCallback;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.CurrentTrack;
import com.osmium.sound.companion.model.JiveItem;
import com.osmium.sound.companion.model.PlayerState;
import com.osmium.sound.companion.model.SlimCommand;
import com.osmium.sound.companion.model.Song;
import com.osmium.sound.companion.service.ISqueezeService;
import com.osmium.sound.companion.service.event.HandshakeComplete;
import com.osmium.sound.companion.util.ImageFetcher;

/**
 * The bespoke kiosk-style album page, mirroring native-ui-qt {@code AlbumPage.qml}: cover and
 * details, the play / shuffle / queue buttons, and the track list (the playing track marked). It
 * lives inside the kiosk shell (breadcrumb, tabs and mini player stay put) and loads the tracks
 * with a raw {@code titles album_id:X} query routed to a {@code Song} callback. v1 shows what
 * Lyrion provides; the appliance's richer metadata (first release, credits, Wikipedia) is not
 * fetched here.
 */
public class AlbumPageFragment extends Fragment implements IServiceItemListCallback<Song> {

    private static final String ARG_ALBUM_ID = "albumId";
    private static final String ARG_TITLE = "albumTitle";
    private static final String ARG_ARTIST = "albumArtist";
    private static final String ARG_COVER = "albumCover";

    /** Lyrion title tags: artist(a), album(l), album_id(e), bitrate(r), tracknum(t), samplerate(T), year(y), duration(d). */
    private static final String TITLE_TAGS = "adelrtTy";

    private String albumId;
    private String albumTitle;
    private String albumArtist;
    private Uri coverUri;

    private ImageView cover;
    private TextView titleView;
    private TextView artistsView;
    private TextView metaView;
    private TextView formatView;
    private ProgressBar loading;
    private RecyclerView trackList;
    private TrackAdapter adapter;

    private boolean loaded;

    public static AlbumPageFragment newInstance(JiveItem album) {
        AlbumPageFragment fragment = new AlbumPageFragment();
        Bundle args = new Bundle();
        args.putString(ARG_ALBUM_ID, album != null ? album.getAlbumId() : null);
        args.putString(ARG_TITLE, album != null ? album.getName() : null);
        args.putString(ARG_ARTIST, album != null ? album.text2() : null);
        args.putParcelable(ARG_COVER, album != null ? album.getIcon() : null);
        fragment.setArguments(args);
        return fragment;
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Bundle args = getArguments();
        if (args != null) {
            albumId = args.getString(ARG_ALBUM_ID);
            albumTitle = args.getString(ARG_TITLE);
            albumArtist = args.getString(ARG_ARTIST);
            coverUri = args.getParcelable(ARG_COVER);
        }
    }

    @NonNull
    private BaseActivity host() {
        return (BaseActivity) requireActivity();
    }

    @Nullable
    private ISqueezeService service() {
        return host().getService();
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.kiosk_album_page, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        cover = view.findViewById(R.id.album_cover);
        titleView = view.findViewById(R.id.album_title);
        artistsView = view.findViewById(R.id.album_artists);
        metaView = view.findViewById(R.id.album_meta);
        formatView = view.findViewById(R.id.album_format);
        loading = view.findViewById(R.id.album_loading);
        trackList = view.findViewById(R.id.album_tracks);

        trackList.setLayoutManager(new LinearLayoutManager(host()));
        adapter = new TrackAdapter();
        trackList.setAdapter(adapter);

        titleView.setText(albumTitle);
        if (albumArtist != null && !albumArtist.isEmpty()) {
            artistsView.setText(albumArtist);
            artistsView.setVisibility(View.VISIBLE);
        } else {
            artistsView.setVisibility(View.GONE);
        }
        if (coverUri != null && !Uri.EMPTY.equals(coverUri)) {
            ImageFetcher.getInstance(host()).loadImage(coverUri, cover);
        }

        view.findViewById(R.id.btn_play).setOnClickListener(v -> playAlbum("load", false));
        view.findViewById(R.id.btn_shuffle).setOnClickListener(v -> playAlbum("load", true));
        view.findViewById(R.id.btn_add).setOnClickListener(v -> playAlbum("add", false));
        view.findViewById(R.id.btn_play_next).setOnClickListener(v -> playAlbum("insert", false));

        // The shell's sticky handshake event replays here if already connected, kicking off the
        // first load; a later connect fires the same observer.
        host().repository().observe(getViewLifecycleOwner(), (HandshakeComplete event) -> load());
        if (service() != null && service().isConnected()) {
            load();
        }
    }

    private void load() {
        if (loaded || albumId == null) return;
        ISqueezeService service = service();
        if (service == null || !service.isConnected()) return;
        loaded = true;
        SlimCommand command = new SlimCommand()
                .cmd("titles")
                .param("album_id", albumId)
                .param("tags", TITLE_TAGS)
                .param("sort", "tracknum");
        service.requestItems(command, this);
    }

    // --- Playback -------------------------------------------------------------------------------

    /** Album-wide playback: {@code playlistcontrol cmd:load|add|insert album_id:X} (+ shuffle). */
    private void playAlbum(String cmd, boolean shuffle) {
        ISqueezeService service = service();
        if (service == null || albumId == null) return;
        Action.JsonAction a = new Action.JsonAction();
        a.cmd("playlistcontrol");
        a.param("cmd", cmd);
        a.param("album_id", albumId);
        service.action(a);
        if (shuffle) {
            Action.JsonAction s = new Action.JsonAction();
            s.cmd("playlist", "shuffle", "1");
            service.action(s);
        }
    }

    /** Track playback: {@code playlistcontrol cmd:load|add|insert track_id:X}. */
    private void playTrack(String cmd, String trackId) {
        ISqueezeService service = service();
        if (service == null || trackId == null) return;
        Action.JsonAction a = new Action.JsonAction();
        a.cmd("playlistcontrol");
        a.param("cmd", cmd);
        a.param("track_id", trackId);
        service.action(a);
    }

    private String currentTrackId() {
        ISqueezeService service = service();
        PlayerState state = (service != null ? service.getActivePlayerState() : null);
        CurrentTrack current = (state != null ? state.getCurrentTrack() : null);
        return (current != null && current.songInfo != null) ? current.songInfo.id : null;
    }

    // --- IServiceItemListCallback<Song> ---------------------------------------------------------

    @Override
    public void onItemsReceived(int count, int start, Map<String, Object> parameters,
                                List<Song> items, Class<Song> dataType) {
        if (!isAdded()) return;
        host().runOnUiThread(() -> bindTracks(items));
    }

    @Override
    public Object getClient() {
        return this;
    }

    private void bindTracks(List<Song> songs) {
        if (!isAdded()) return;
        loading.setVisibility(View.GONE);
        adapter.setSongs(songs);

        int total = 0;
        String year = "";
        String format = "";
        String artist = albumArtist;
        for (Song s : songs) {
            total += s.duration;
            if (year.isEmpty() && !s.year.isEmpty() && !"0".equals(s.year)) year = s.year;
            if (format.isEmpty()) format = describeFormat(s);
            if ((artist == null || artist.isEmpty()) && !s.getArtist().isEmpty()) artist = s.getArtist();
        }

        if (artist != null && !artist.isEmpty()) {
            artistsView.setText(artist);
            artistsView.setVisibility(View.VISIBLE);
        }

        int n = songs.size();
        String tracks = getString(n == 1 ? R.string.kiosk_album_tracks_one
                : R.string.kiosk_album_tracks_other, n);
        StringBuilder meta = new StringBuilder();
        if (!year.isEmpty()) meta.append(year).append(" · ");
        meta.append(tracks);
        if (total > 0) meta.append(" · ").append(Util.formatElapsedTime(total));
        metaView.setText(meta);

        if (!format.isEmpty()) {
            formatView.setText(format);
            formatView.setVisibility(View.VISIBLE);
        } else {
            formatView.setVisibility(View.GONE);
        }
    }

    /** "96 kHz" / "320" (kbps) when Lyrion reports them, else empty. */
    private String describeFormat(Song s) {
        String sampleRate = s.getSampleRate();
        if (sampleRate != null && !sampleRate.isEmpty()) return sampleRate;
        String bitRate = s.getBitRate();
        return (bitRate != null && !bitRate.isEmpty()) ? bitRate : "";
    }

    // --- Track list -----------------------------------------------------------------------------

    private class TrackAdapter extends RecyclerView.Adapter<TrackViewHolder> {

        private final List<Song> songs = new ArrayList<>();

        void setSongs(List<Song> items) {
            songs.clear();
            if (items != null) songs.addAll(items);
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public TrackViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View v = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.kiosk_album_track_row, parent, false);
            return new TrackViewHolder(v);
        }

        @Override
        public void onBindViewHolder(@NonNull TrackViewHolder holder, int position) {
            holder.bind(songs.get(position));
        }

        @Override
        public int getItemCount() {
            return songs.size();
        }
    }

    private class TrackViewHolder extends RecyclerView.ViewHolder {
        final TextView number;
        final TextView title;
        final TextView subtitle;
        final TextView duration;

        TrackViewHolder(@NonNull View itemView) {
            super(itemView);
            number = itemView.findViewById(R.id.track_number);
            title = itemView.findViewById(R.id.track_title);
            subtitle = itemView.findViewById(R.id.track_subtitle);
            duration = itemView.findViewById(R.id.track_duration);
        }

        void bind(Song song) {
            boolean playing = song.id != null && song.id.equals(currentTrackId());
            if (playing) {
                number.setText("▶");
                number.setTextColor(getResources().getColor(R.color.osmium_gold, null));
                title.setTextColor(getResources().getColor(R.color.osmium_gold, null));
            } else {
                number.setText(String.valueOf(song.trackNum));
                number.setTextColor(getResources().getColor(R.color.osmium_silver, null));
                title.setTextColor(0xFFFFFFFF);
            }
            title.setText(song.title);

            String sub = trackSubtitle(song);
            if (sub.isEmpty()) {
                subtitle.setVisibility(View.GONE);
            } else {
                subtitle.setText(sub);
                subtitle.setVisibility(View.VISIBLE);
            }

            duration.setText(song.duration > 0 ? Util.formatElapsedTime(song.duration) : "");

            itemView.setOnClickListener(v -> playTrack("load", song.id));
            itemView.setOnLongClickListener(v -> {
                showTrackMenu(v, song);
                return true;
            });
        }
    }

    /** Track sub-line: the track artist when it differs from the album artist, else the composer. */
    private String trackSubtitle(Song song) {
        String trackArtist = song.getArtist();
        if (!trackArtist.isEmpty() && (albumArtist == null || !trackArtist.equals(albumArtist))) {
            return trackArtist;
        }
        return song.getComposer();
    }

    private void showTrackMenu(View anchor, Song song) {
        PopupMenu menu = new PopupMenu(anchor.getContext(), anchor);
        menu.getMenu().add(0, 1, 0, R.string.kiosk_album_add);
        menu.getMenu().add(0, 2, 1, R.string.kiosk_album_play_next);
        menu.setOnMenuItemClickListener(item -> {
            if (item.getItemId() == 1) {
                playTrack("add", song.id);
            } else if (item.getItemId() == 2) {
                playTrack("insert", song.id);
            }
            return true;
        });
        menu.show();
    }
}
