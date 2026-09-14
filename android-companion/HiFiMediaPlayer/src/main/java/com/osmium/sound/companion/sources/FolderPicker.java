package com.osmium.sound.companion.sources;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.android.material.button.MaterialButton;

import org.json.JSONArray;
import org.json.JSONObject;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.appliance.ApplianceHttpClient;

/**
 * Folder picker over sources_server.py's /api/local/browse — the same widget
 * "add a local folder", "share a local folder" and "playlist folder" all use.
 * Each instance keeps its own browse position. Mirrors the web admin's
 * FolderPicker.vue.
 */
public final class FolderPicker {
    public interface Listener {
        void onPick(String path);
        void onError(String message);
        /** Whether the owning screen is busy with another request (disables "pick"). */
        boolean isBusy();
    }

    private final SourcesApi api;
    private final Listener listener;
    private final View root;
    private final TextView pathView;
    private final MaterialButton upButton;
    private final TextView loadingView;
    private final TextView emptyView;
    private final LinearLayout dirsView;
    private final EditText newName;
    private final MaterialButton createButton;
    private final MaterialButton pickButton;

    private String path;
    private String parent;           // null: already at the top
    private boolean loading;
    private boolean detached;

    public FolderPicker(ViewGroup container, SourcesApi api, String pickLabel, String startAt, Listener listener) {
        this.api = api;
        this.listener = listener;
        LayoutInflater inflater = LayoutInflater.from(container.getContext());
        root = inflater.inflate(R.layout.sources_folder_picker, container, false);
        container.addView(root);

        pathView = root.findViewById(R.id.sources_picker_path);
        upButton = root.findViewById(R.id.sources_picker_up);
        loadingView = root.findViewById(R.id.sources_picker_loading);
        emptyView = root.findViewById(R.id.sources_picker_empty);
        dirsView = root.findViewById(R.id.sources_picker_dirs);
        newName = root.findViewById(R.id.sources_picker_new_name);
        createButton = root.findViewById(R.id.sources_picker_create);
        pickButton = root.findViewById(R.id.sources_picker_pick);

        pickButton.setText(pickLabel);
        upButton.setOnClickListener(v -> {
            if (parent != null) browse(parent);
        });
        createButton.setOnClickListener(v -> createHere());
        pickButton.setOnClickListener(v -> {
            if (!listener.isBusy() && path != null && !path.isEmpty()) listener.onPick(path);
        });

        path = startAt != null ? startAt : "";
        browse(path);
    }

    /** Stop reacting to replies still in flight once the screen holding this picker is gone. */
    public void detach() {
        detached = true;
    }

    private void browse(String next) {
        setLoading(true);
        api.localBrowse(next != null ? next : "", new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (detached) return;
                setLoading(false);
                if (SourcesApi.failed(body) || !body.has("dirs")) {
                    listener.onError(SourcesApi.message(body, root.getContext().getString(R.string.sources_common_error)));
                    return;
                }
                path = SourcesApi.str(body, "path");
                parent = body.isNull("parent") ? null : body.optString("parent", null);
                render(body.optJSONArray("dirs"));
            }

            @Override
            public void onFailure(String message) {
                if (detached) return;
                setLoading(false);
                listener.onError(root.getContext().getString(R.string.sources_common_error) + ": " + message);
            }
        });
    }

    private void createHere() {
        String name = newName.getText().toString().trim();
        if (name.isEmpty() || path == null || path.isEmpty() || loading) return;
        setLoading(true);
        api.localMkdir(path, name, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (detached) return;
                setLoading(false);
                if (SourcesApi.failed(body) || !body.has("path")) {
                    listener.onError(SourcesApi.message(body, root.getContext().getString(R.string.sources_common_error)));
                    return;
                }
                newName.setText("");
                browse(body.optString("path", path));
            }

            @Override
            public void onFailure(String message) {
                if (detached) return;
                setLoading(false);
                listener.onError(root.getContext().getString(R.string.sources_common_error) + ": " + message);
            }
        });
    }

    private void render(JSONArray dirs) {
        pathView.setText(path == null || path.isEmpty() ? "/" : path);
        dirsView.removeAllViews();
        int n = dirs != null ? dirs.length() : 0;
        emptyView.setVisibility(n == 0 ? View.VISIBLE : View.GONE);
        LayoutInflater inflater = LayoutInflater.from(root.getContext());
        for (int i = 0; i < n; i++) {
            String dir = dirs.optString(i, "");
            if (dir.isEmpty()) continue;
            View row = inflater.inflate(R.layout.sources_folder_row, dirsView, false);
            // The listing hands back full paths; show just the last segment.
            String shown = dir.endsWith("/") ? dir.substring(0, dir.length() - 1) : dir;
            int slash = shown.lastIndexOf('/');
            ((TextView) row.findViewById(R.id.sources_folder_name))
                    .setText(slash >= 0 && slash < shown.length() - 1 && path != null && !"/".equals(path)
                            ? shown.substring(slash + 1) : dir);
            row.setOnClickListener(v -> browse(dir));
            dirsView.addView(row);
        }
        updateButtons();
    }

    private void setLoading(boolean value) {
        loading = value;
        loadingView.setVisibility(value ? View.VISIBLE : View.GONE);
        dirsView.setVisibility(value ? View.GONE : View.VISIBLE);
        if (value) emptyView.setVisibility(View.GONE);
        updateButtons();
    }

    private void updateButtons() {
        boolean hasPath = path != null && !path.isEmpty();
        upButton.setEnabled(parent != null && !loading);
        createButton.setEnabled(!loading && hasPath);
        pickButton.setEnabled(hasPath && !loading);
    }
}
