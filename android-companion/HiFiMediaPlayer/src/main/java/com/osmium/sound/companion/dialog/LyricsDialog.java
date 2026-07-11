package com.osmium.sound.companion.dialog;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import java.util.List;
import java.util.Locale;
import java.util.Map;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.framework.BottomSheetDialogFragmentWithService;
import com.osmium.sound.companion.itemlist.IServiceItemListCallback;
import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;

/**
 * Shows lyrics for the current track, if the connected server exposes them
 * (e.g. via the MusicArtistInfo plugin's trackinfo entry). Reuses the same
 * "more" context-menu browse mechanism as {@link com.osmium.sound.companion.framework.ContextMenu}
 * (the current track's {@code moreAction}) rather than a bespoke command,
 * since that's the standard extension point LMS/Lyrion plugins use to add
 * per-track info panels — there's no dedicated "lyrics" tag in the base
 * protocol (see JiveItem#SONG_TAGS).
 * <p>
 * The entry is located by matching its name against "lyric"/"testi"
 * case-insensitively, since the exact label depends on the plugin and the
 * server's configured language. If the server has no lyrics plugin, or the
 * current track has no lyrics, this shows a "not available" message rather
 * than failing.
 */
public class LyricsDialog extends BottomSheetDialogFragmentWithService implements IServiceItemListCallback<JiveItem> {
    private static final String ARG_MORE_ACTION = "more_action";

    private ProgressBar progress;
    private View scroll;
    private TextView text;
    private boolean drilledDown;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.dialog_lyrics, container, false);
        progress = view.findViewById(R.id.lyrics_progress);
        scroll = view.findViewById(R.id.lyrics_scroll);
        text = view.findViewById(R.id.lyrics_text);
        return view;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        Action moreAction = requireArguments().getParcelable(ARG_MORE_ACTION);
        if (moreAction == null) {
            showText(getString(R.string.menu_item_lyrics_unavailable));
            return;
        }
        requireService().pluginItems(moreAction, this);
    }

    @Override
    public void onItemsReceived(int count, int start, Map<String, Object> parameters, List<JiveItem> items, Class<JiveItem> dataType) {
        if (!drilledDown) {
            JiveItem lyricsItem = findLyricsItem(items);
            if (lyricsItem == null || lyricsItem.goAction == null) {
                showText(getString(R.string.menu_item_lyrics_unavailable));
                return;
            }
            drilledDown = true;
            requireService().pluginItems(0, lyricsItem, lyricsItem.goAction, this);
            return;
        }

        StringBuilder lyrics = new StringBuilder();
        for (JiveItem item : items) {
            String line = item.getName();
            if (line == null || line.isEmpty()) continue;
            if (lyrics.length() > 0) lyrics.append('\n');
            lyrics.append(line);
        }
        showText(lyrics.length() > 0 ? lyrics.toString() : getString(R.string.menu_item_lyrics_unavailable));
    }

    private static JiveItem findLyricsItem(List<JiveItem> items) {
        for (JiveItem item : items) {
            String name = item.getName();
            if (name == null) continue;
            String lower = name.toLowerCase(Locale.ROOT);
            if (lower.contains("lyric") || lower.contains("testi")) {
                return item;
            }
        }
        return null;
    }

    private void showText(String value) {
        if (!isAdded()) return;
        requireActivity().runOnUiThread(() -> {
            progress.setVisibility(View.GONE);
            scroll.setVisibility(View.VISIBLE);
            text.setText(value);
        });
    }

    @Override
    public Object getClient() {
        return this;
    }

    public static void show(FragmentManager fragmentManager, @Nullable Action moreAction) {
        if (fragmentManager.isDestroyed()) return;
        LyricsDialog dialog = new LyricsDialog();
        Bundle args = new Bundle();
        args.putParcelable(ARG_MORE_ACTION, moreAction);
        dialog.setArguments(args);
        dialog.show(fragmentManager, LyricsDialog.class.getSimpleName());
    }
}
