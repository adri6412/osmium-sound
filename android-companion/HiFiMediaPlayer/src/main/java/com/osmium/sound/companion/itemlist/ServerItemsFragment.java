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

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;

/**
 * The Radio and Apps tab roots, filled from the LMS commands {@code radios 0 9999} and
 * {@code apps 0 9999} — exactly what the Qt kiosk does (native-ui-qt {@code LibraryModel::Radios}
 * / {@code Apps}). These commands work on every server, grouped or not, unlike filtering the
 * sticky home menu by node (which only finds anything on a grouped server).
 *
 * <p>The catch: the shared JiveItem browse path only parses {@code item_loop}
 * ({@code CometClient.JiveItemListener}), while {@code radios}/{@code apps} answer with
 * {@code radioss_loop}/{@code appss_loop} (rows keyed by {@code cmd} and {@code name}). So we send
 * the command (with {@code menu:1}, which a server that supports it answers with a rich
 * {@code item_loop} we use verbatim) and, when that yields no items, build the rows ourselves from
 * the alternate loop and forge each one's drill-in action {@code <cmd> items … menu:1} (which
 * returns {@code item_loop}, handled by the normal {@link JiveItemListFragment}).
 */
public class ServerItemsFragment extends JiveItemListFragment {

    private static final String ARG_CMD = "serverItemsCmd";

    /** Response loop names to try, in order, per command when {@code item_loop} is empty. */
    private static final String[] RADIOS_LOOPS = {"radioss_loop", "radios_loop"};
    private static final String[] APPS_LOOPS = {"appss_loop", "apps_loop"};

    private String cmd;

    /**
     * @param cmd   the server command, {@code "radios"} or {@code "apps"}
     * @param title the breadcrumb label for this tab root
     */
    public static ServerItemsFragment newInstance(String cmd, String title) {
        ServerItemsFragment fragment = new ServerItemsFragment();
        Map<String, Object> record = new HashMap<>();
        record.put("name", title);
        JiveItem parent = new JiveItem(record);
        Bundle args = new Bundle();
        // Same argument keys JiveItemListFragment.onCreate reads.
        args.putParcelable(JiveItem.class.getName(), parent);
        args.putParcelable(Action.class.getName(), browseAction(new String[]{cmd}));
        args.putString(ARG_CMD, cmd);
        fragment.setArguments(args);
        return fragment;
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Bundle args = getArguments();
        if (args != null) {
            cmd = args.getString(ARG_CMD);
        }
    }

    @Override
    public void onItemsReceived(int count, int start, Map<String, Object> parameters,
                                List<JiveItem> items, Class<JiveItem> dataType) {
        // Server honoured menu:1 and answered with a normal item_loop: use it as-is (the rows carry
        // the server's own go actions, so drill-in needs no forging).
        if (items != null && !items.isEmpty()) {
            super.onItemsReceived(count, start, parameters, items, dataType);
            return;
        }
        List<JiveItem> built = buildFromAlternateLoop(parameters);
        if (built.isEmpty()) {
            // Nothing in either shape: let the base show its empty-list message.
            super.onItemsReceived(count, start, parameters, items, dataType);
            return;
        }
        super.onItemsReceived(built.size(), 0, parameters, built, dataType);
    }

    /** Builds rows from radioss_loop/appss_loop (or the _loop fallback), each with a drill-in action. */
    private List<JiveItem> buildFromAlternateLoop(Map<String, Object> parameters) {
        List<JiveItem> built = new ArrayList<>();
        String[] loopNames = "radios".equals(cmd) ? RADIOS_LOOPS : APPS_LOOPS;
        List<?> loop = null;
        for (String name : loopNames) {
            Object value = parameters.get(name);
            if (value instanceof List<?> list && !list.isEmpty()) {
                loop = list;
                break;
            }
        }
        if (loop == null) return built;
        for (Object entry : loop) {
            if (!(entry instanceof Map<?, ?> rowMap)) continue;
            @SuppressWarnings("unchecked")
            JiveItem row = new JiveItem((Map<String, Object>) rowMap);
            // JiveItem(Map) reads cmd->id and name->text; the plugin command is the item id.
            if (row.getId() == null || row.getId().isEmpty()) continue;
            row.goAction = browseAction(new String[]{row.getId(), "items"});
            built.add(row);
        }
        return built;
    }

    /** A forged browse action ({@code <cmd…> menu:1}), mirroring {@code HomeTilesFragment.openTile}. */
    private static Action browseAction(String[] cmd) {
        Action.JsonAction json = new Action.JsonAction();
        json.cmd(cmd);
        json.param("menu", "1");
        // Forged actions must carry a (possibly empty) players array: Action.isPlayerSpecific()
        // reads players.length with no null guard, so a null here NPEs the active-player observer
        // and resets the app (see companion-kiosk-redesign note / commit 02f5f83).
        json.players = new String[0];
        Action action = new Action();
        action.action = json;
        return action;
    }
}
