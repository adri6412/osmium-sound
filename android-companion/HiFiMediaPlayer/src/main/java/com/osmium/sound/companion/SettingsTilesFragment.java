package com.osmium.sound.companion;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

import com.osmium.sound.companion.widget.GridAutofitLayoutManager;

/**
 * One level of the Settings tile grid: the macro groups when no group is
 * given, otherwise the sections of that group. Tiles follow the kiosk's Settings
 * (native-ui-qt SettingsTab.qml): a square card with the icon, the name and,
 * for a group, a one-line preview of what it holds.
 */
public class SettingsTilesFragment extends Fragment {
    private static final String ARG_GROUP = "group";

    private final List<Tile> tiles = new ArrayList<>();
    private RecyclerView list;

    public static SettingsTilesFragment newInstance(@Nullable String groupId) {
        SettingsTilesFragment fragment = new SettingsTilesFragment();
        Bundle args = new Bundle();
        if (groupId != null) args.putString(ARG_GROUP, groupId);
        fragment.setArguments(args);
        return fragment;
    }

    /** One tile: what it shows and what a tap does. */
    private static final class Tile {
        final int icon;
        final String title;
        final String preview;
        final Runnable onClick;

        Tile(int icon, String title, @Nullable String preview, Runnable onClick) {
            this.icon = icon;
            this.title = title;
            this.preview = preview;
            this.onClick = onClick;
        }
    }

    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.settings_tiles, container, false);
        list = view.findViewById(R.id.settings_tiles);
        list.setLayoutManager(new GridAutofitLayoutManager(requireContext(), R.dimen.settings_tile_column_width));
        list.setAdapter(new TileAdapter());
        return view;
    }

    @Override
    public void onResume() {
        super.onResume();
        rebuildTiles();
        list.getAdapter().notifyDataSetChanged();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        list = null;
    }

    /**
     * Rebuilt on every resume: whether the device is an Osmium Sound appliance
     * can change while the app is away (a new server chosen in the wizard).
     */
    private void rebuildTiles() {
        tiles.clear();
        boolean appliance = HiFiMediaPlayer.getPreferences().isOsmiumAppliance();
        SettingsActivity activity = (SettingsActivity) requireActivity();
        String groupId = requireArguments().getString(ARG_GROUP);

        if (groupId == null) {
            for (SettingsCatalog.Group group : SettingsCatalog.GROUPS) {
                List<SettingsCatalog.Section> sections = group.visibleSections(appliance);
                if (sections.isEmpty()) continue;
                tiles.add(new Tile(group.icon, getString(group.title), preview(sections),
                        () -> activity.openGroup(group)));
            }
            return;
        }

        SettingsCatalog.Group group = SettingsCatalog.group(groupId);
        if (group == null) return;
        for (SettingsCatalog.Section section : group.visibleSections(appliance)) {
            tiles.add(new Tile(section.icon, getString(section.title), null,
                    () -> activity.openSection(section)));
        }
    }

    /** "Sources · Library · Playback" under a group tile, as the kiosk does. */
    private String preview(List<SettingsCatalog.Section> sections) {
        StringBuilder out = new StringBuilder();
        for (SettingsCatalog.Section section : sections) {
            if (out.length() > 0) out.append(" · ");
            out.append(getString(section.title));
        }
        return out.toString();
    }

    private final class TileAdapter extends RecyclerView.Adapter<TileHolder> {
        @NonNull
        @Override
        public TileHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.settings_tile, parent, false);
            return new TileHolder(view);
        }

        @Override
        public void onBindViewHolder(@NonNull TileHolder holder, int position) {
            holder.bind(tiles.get(position));
        }

        @Override
        public int getItemCount() {
            return tiles.size();
        }
    }

    private static final class TileHolder extends RecyclerView.ViewHolder {
        private final ImageView icon;
        private final TextView title;
        private final TextView preview;

        TileHolder(@NonNull View itemView) {
            super(itemView);
            icon = itemView.findViewById(R.id.settings_tile_icon);
            title = itemView.findViewById(R.id.settings_tile_title);
            preview = itemView.findViewById(R.id.settings_tile_preview);
        }

        void bind(Tile tile) {
            icon.setImageResource(tile.icon);
            title.setText(tile.title);
            preview.setText(tile.preview);
            preview.setVisibility(tile.preview == null ? View.GONE : View.VISIBLE);
            itemView.setOnClickListener(v -> tile.onClick.run());
        }
    }
}
