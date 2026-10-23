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
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.annotation.DrawableRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.itemlist.JiveItemListActivity;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;

/**
 * The Music tab's home: a fixed grid of library categories, the same set and
 * order as the kiosk (native-ui-qt/qml/Browser.qml {@code tiles}). Tapping a
 * tile opens that library listing. For now it reuses the themed list screen
 * ({@link JiveItemListActivity}); the dedicated in-container library views come
 * with the next milestone.
 */
public class HomeTilesFragment extends Fragment {

    /** A home tile: an icon, a label and the CLI command that fills its list. */
    private static final class Tile {
        @DrawableRes final int icon;
        @StringRes final int label;
        final String[] cmd;
        /** Flat key/value pairs turned into command params. */
        final String[] params;

        Tile(@DrawableRes int icon, @StringRes int label, String[] cmd, String[] params) {
            this.icon = icon;
            this.label = label;
            this.cmd = cmd;
            this.params = params;
        }
    }

    private static final String[] BROWSE = {"browselibrary", "items"};

    private static final List<Tile> TILES = Arrays.asList(
            new Tile(R.drawable.favorites, R.string.kiosk_tile_favorites,
                    new String[]{"favorites", "items"}, new String[]{"menu", "1"}),
            new Tile(R.drawable.ml_artists, R.string.kiosk_tile_artists,
                    BROWSE, new String[]{"mode", "artists", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_albums, R.string.kiosk_tile_albums,
                    BROWSE, new String[]{"mode", "albums", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_genres, R.string.kiosk_tile_genres,
                    BROWSE, new String[]{"mode", "genres", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_years, R.string.kiosk_tile_years,
                    BROWSE, new String[]{"mode", "years", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_artists_composer, R.string.kiosk_tile_composers,
                    BROWSE, new String[]{"mode", "artists", "role_id", "COMPOSER", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_new_music, R.string.kiosk_tile_new_music,
                    BROWSE, new String[]{"mode", "albums", "sort", "new", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_folder, R.string.kiosk_tile_folders,
                    BROWSE, new String[]{"mode", "bmf", "menu", "1", "useContextMenu", "1"}),
            new Tile(R.drawable.ml_playlist, R.string.kiosk_tile_playlists,
                    BROWSE, new String[]{"mode", "playlists", "menu", "1", "useContextMenu", "1"}));

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        RecyclerView grid = (RecyclerView) inflater.inflate(R.layout.kiosk_home, container, false);
        grid.setLayoutManager(new GridLayoutManager(requireContext(), 3));
        grid.setAdapter(new TileAdapter());
        return grid;
    }

    /** Opens the library listing for a tile, reusing the themed list screen. */
    private void openTile(Tile tile) {
        Activity activity = getActivity();
        if (activity == null) return;
        Action.JsonAction json = new Action.JsonAction();
        json.cmd(tile.cmd);
        for (int i = 0; i + 1 < tile.params.length; i += 2) {
            json.param(tile.params[i], tile.params[i + 1]);
        }
        Action action = new Action();
        action.action = json;
        // Build the header item through the record constructor so every field the
        // list header reads (choiceStrings, text2, ...) is initialised; the bare
        // constructor leaves them null and updateHeader() then NPEs.
        Map<String, Object> record = new HashMap<>();
        record.put("name", getString(tile.label));
        JiveItem parent = new JiveItem(record);
        JiveItemListActivity.show(activity, parent, action);
    }

    private final class TileAdapter extends RecyclerView.Adapter<TileAdapter.TileHolder> {
        @NonNull
        @Override
        public TileHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View view = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.kiosk_home_tile, parent, false);
            return new TileHolder(view);
        }

        @Override
        public void onBindViewHolder(@NonNull TileHolder holder, int position) {
            Tile tile = TILES.get(position);
            holder.icon.setImageResource(tile.icon);
            holder.label.setText(tile.label);
            holder.itemView.setOnClickListener(v -> openTile(tile));
        }

        @Override
        public int getItemCount() {
            return TILES.size();
        }

        final class TileHolder extends RecyclerView.ViewHolder {
            final ImageView icon;
            final TextView label;

            TileHolder(@NonNull View itemView) {
                super(itemView);
                icon = itemView.findViewById(R.id.tile_icon);
                label = itemView.findViewById(R.id.tile_label);
            }
        }
    }
}
