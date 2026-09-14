package com.osmium.sound.companion;

import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.activity.OnBackPressedCallback;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.switchmaterial.SwitchMaterial;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.sources.FolderPicker;
import com.osmium.sound.companion.sources.FormatDiskDialog;
import com.osmium.sound.companion.sources.SmbHowtoDialog;
import com.osmium.sound.companion.sources.SourcesApi;
import com.osmium.sound.companion.sources.SourcesFormat;
import com.osmium.sound.companion.sources.TextChanged;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Settings → Music sources, a port of the web admin's SourcesPanel.vue (and the
 * kiosk's SourcesManager): active sources, add a source (network folder with a
 * LAN scan, internal disk, local folder), playlist folder and the folders this
 * player shares on the network.
 * <p>
 * One screen at a time with a way back, like the web admin: {@link #nav} is where
 * we are ([] is the menu, ["add", "smb"] the network-folder flow). There is no
 * "Apply" button: sources_server.py pushes every edit into Lyrion's live media
 * folders and rescans on its own, without restarting playback.
 * <p>
 * Talks to sources_server.py directly through {@link SourcesApi}.
 */
public class SourcesActivity extends AppCompatActivity {
    private static final long SOURCES_POLL_MS = 4000;
    private static final long INTERNAL_POLL_MS = 5000;
    private static final long SCAN_POLL_MS = 900;
    private static final long MESSAGE_CLEAR_MS = 6000;
    private static final String BAD_CREDENTIALS = "msg.smbBadCredentials";

    private final ThemeManager mThemeManager = new ThemeManager();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private SourcesApi api;
    private boolean destroyed;

    private MaterialToolbar toolbar;
    private ScrollView scrollView;
    private TextView autoApplyHint;
    private LinearLayout content;
    private ProgressBar progressBar;
    private TextView messageView;
    private OnBackPressedCallback backCallback;

    private final List<String> nav = new ArrayList<>();
    private boolean busy;

    // ── Data from the appliance ────────────────────────────────────────
    private JSONArray sources = new JSONArray();
    private String sourcesJson = "";
    private JSONArray usb = new JSONArray();
    private String usbJson = "";
    private JSONArray internalDisks = new JSONArray();
    private String disksJson = "";
    @Nullable private JSONObject smbCard;          // null: not loaded, or no such endpoint
    private String playlistdir = "";
    private String playlistdirDefault = "";
    private boolean playlistSupported;

    // ── Views of the screen on show (null when another screen is up) ──
    private TextView menuActiveSub;
    private View menuPlaylistRow;
    private View menuShareRow;
    private LinearLayout activeList;
    private LinearLayout disksList;
    private View playlistPage;
    private boolean playlistPickerOpen;
    private View sharePage;
    private View wizRoot;
    @Nullable private FolderPicker picker;

    // ── Subfolder browser for one smb/internal/usb source ──────────────
    @Nullable private String browsingId;
    private String browsePath = "";
    private JSONArray browseDirs = new JSONArray();
    @Nullable private String browseParent;
    private boolean browseBusy;

    // ── Guided "add a network folder" ──────────────────────────────────
    private int wizStep;                 // 0 find a device, 1 pick a folder, 2 confirm
    private boolean wizManual;           // "I'll type it myself"
    private String wizHost = "";
    private String wizName = "";
    private String wizShare = "";
    private String wizUser = "";
    private String wizPass = "";
    private boolean wizRw;
    private boolean wizBusy;
    private String wizErr = "";
    private String wizDetail = "";
    private boolean wizDetailOpen;
    private boolean wizNeedsAuth;
    private boolean wizCanList = true;   // false when this server's shares cannot be read
    private boolean wizNoClient;         // ...because the appliance has no smbclient at all
    private int wizToken;                // bumped on reset: replies to an older flow are dropped
    private String scanState = "";
    private int scanProgress;
    private JSONArray scanHosts = new JSONArray();
    private JSONArray wizShares = new JSONArray();
    private boolean scanPolling;
    @Nullable private AlertDialog loginDialog;
    @Nullable private FormatDiskDialog formatDialog;

    private final Runnable sourcesPoll = new Runnable() {
        @Override
        public void run() {
            loadSources(null);
            loadUsb();
            handler.postDelayed(this, SOURCES_POLL_MS);
        }
    };

    private final Runnable internalPoll = new Runnable() {
        @Override
        public void run() {
            loadInternal();
            handler.postDelayed(this, INTERNAL_POLL_MS);
        }
    };

    private final Runnable scanPoll = this::wizPoll;
    private final Runnable clearMessage = () -> say("", false);

    /** JSON callback that does nothing once the screen is gone. */
    private abstract class Cb implements ApplianceHttpClient.JsonCallback {
        abstract void ok(JSONObject body);

        void fail(String message) {
            say(getString(R.string.sources_common_error) + ": " + message, true);
        }

        @Override
        public final void onSuccess(JSONObject body) {
            if (!destroyed) ok(body);
        }

        @Override
        public final void onFailure(String message) {
            if (!destroyed) fail(message);
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        setContentView(R.layout.activity_sources);
        toolbar = findViewById(R.id.toolbar);
        setSupportActionBar(toolbar);
        ViewUtilities.setInsetsListener(toolbar, true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.sources_container), false, true, false);

        api = new SourcesApi(this);
        scrollView = findViewById(R.id.sources_container);
        autoApplyHint = findViewById(R.id.sources_auto_apply_hint);
        content = findViewById(R.id.sources_content);
        progressBar = findViewById(R.id.sources_progress);
        messageView = findViewById(R.id.sources_message);

        // System back walks up one screen before it leaves the activity.
        backCallback = new OnBackPressedCallback(false) {
            @Override
            public void handleOnBackPressed() {
                back();
            }
        };
        getOnBackPressedDispatcher().addCallback(this, backCallback);

        render();
        loadSmbCard();
        loadPlaylistdir();
    }

    @Override
    public void onResume() {
        super.onResume();
        mThemeManager.onResume(this);
        // Active sources + USB every 4 s, internal disks every 5 s, while on screen.
        handler.removeCallbacks(sourcesPoll);
        handler.removeCallbacks(internalPoll);
        sourcesPoll.run();
        internalPoll.run();
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(sourcesPoll);
        handler.removeCallbacks(internalPoll);
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        handler.removeCallbacksAndMessages(null);
        wizStopScan();
        if (formatDialog != null) formatDialog.dismiss();
        if (loginDialog != null && loginDialog.isShowing()) loginDialog.dismiss();
        detachPicker();
        super.onDestroy();
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            if (nav.isEmpty()) {
                finish();
            } else {
                back();
            }
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    public static void show(Context context) {
        context.startActivity(new Intent(context, SourcesActivity.class));
    }

    // ── Navigation ─────────────────────────────────────────────────────
    private String page() {
        return String.join("/", nav);
    }

    private void go(String key) {
        nav.add(key);
        render();
        // Entering "network folder" starts the LAN scan straight away: the list
        // is the point of that screen.
        if ("add/smb".equals(page())) {
            wizReset();
            wizScan();
        }
    }

    private void back() {
        if (nav.isEmpty()) return;
        String leaving = page();
        nav.remove(nav.size() - 1);
        if ("add/smb".equals(leaving)) {
            wizStopScan();
            wizReset();
        }
        say("", false);
        render();
    }

    /** Jump straight to a screen. */
    private void openPage(String path) {
        nav.clear();
        if (!path.isEmpty()) {
            for (String part : path.split("/")) nav.add(part);
        }
        render();
    }

    private int pageTitle(String page) {
        switch (page) {
            case "active": return R.string.sources_active;
            case "add": return R.string.sources_add_source;
            case "add/smb": return R.string.sources_add_smb;
            case "add/internal": return R.string.sources_internal_title;
            case "add/local": return R.string.sources_add_local;
            case "playlist": return R.string.sources_playlistdir_title;
            case "share": return R.string.sources_share_title;
            case "share/local": return R.string.sources_share_local;
            default: return R.string.sources_title;
        }
    }

    private void render() {
        detachPicker();
        content.removeAllViews();
        menuActiveSub = null;
        menuPlaylistRow = null;
        menuShareRow = null;
        activeList = null;
        disksList = null;
        playlistPage = null;
        playlistPickerOpen = false;
        sharePage = null;
        wizRoot = null;

        String page = page();
        toolbar.setTitle(pageTitle(page));
        autoApplyHint.setVisibility(page.isEmpty() ? View.VISIBLE : View.GONE);
        backCallback.setEnabled(!nav.isEmpty());

        switch (page) {
            case "":
                renderMenuPage();
                break;
            case "active":
                activeList = newColumn(content);
                renderActiveList();
                break;
            case "add":
                addMenuRow(content, 0, getString(R.string.sources_add_smb),
                        getString(R.string.sources_add_smb_hint), v -> go("smb"));
                addMenuRow(content, 0, getString(R.string.sources_internal_title),
                        getString(R.string.sources_add_internal_hint), v -> go("internal"));
                addMenuRow(content, R.drawable.folder, getString(R.string.sources_add_local),
                        getString(R.string.sources_add_local_hint), v -> go("local"));
                break;
            case "add/smb":
                renderWizardPage();
                break;
            case "add/internal":
                disksList = newColumn(content);
                renderDisks();
                break;
            case "add/local":
                picker = new FolderPicker(content, api, getString(R.string.sources_use_this_folder), "",
                        pickerListener(path -> addLocal(path, false)));
                break;
            case "playlist":
                renderPlaylistPage();
                break;
            case "share":
                renderSharePage();
                break;
            case "share/local":
                addText(content, getString(R.string.sources_local_samba_hint), R.color.hifiSilver);
                picker = new FolderPicker(content, api, getString(R.string.sources_share_this_folder), "",
                        pickerListener(path -> addLocal(path, true)));
                break;
            default:
                break;
        }
        scrollView.scrollTo(0, 0);
    }

    private interface PathAction {
        void run(String path);
    }

    private FolderPicker.Listener pickerListener(PathAction onPick) {
        return new FolderPicker.Listener() {
            @Override
            public void onPick(String path) {
                onPick.run(path);
            }

            @Override
            public void onError(String message) {
                say(message, true);
            }

            @Override
            public boolean isBusy() {
                return busy;
            }
        };
    }

    private void detachPicker() {
        if (picker != null) picker.detach();
        picker = null;
    }

    // ── Small view helpers ─────────────────────────────────────────────
    private LinearLayout newColumn(ViewGroup parent) {
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        parent.addView(column, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return column;
    }

    private TextView addText(ViewGroup parent, CharSequence text, int colorRes) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(getColor(colorRes));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        int pad = dp(8);
        lp.setMargins(0, pad, 0, pad);
        parent.addView(view, lp);
        return view;
    }

    private View addMenuRow(ViewGroup parent, int iconRes, CharSequence title, @Nullable CharSequence subtitle,
                            View.OnClickListener onClick) {
        View row = LayoutInflater.from(this).inflate(R.layout.sources_menu_row, parent, false);
        ImageView icon = row.findViewById(R.id.sources_row_icon);
        if (iconRes != 0) {
            icon.setImageResource(iconRes);
            icon.setImageTintList(ColorStateList.valueOf(getColor(R.color.hifiSilver)));
            icon.setVisibility(View.VISIBLE);
        }
        ((TextView) row.findViewById(R.id.sources_row_title)).setText(title);
        setRowSubtitle(row, subtitle);
        row.setOnClickListener(onClick);
        parent.addView(row);
        return row;
    }

    private static void setRowSubtitle(View row, @Nullable CharSequence subtitle) {
        TextView sub = row.findViewById(R.id.sources_row_subtitle);
        sub.setText(subtitle);
        sub.setVisibility(subtitle == null || subtitle.length() == 0 ? View.GONE : View.VISIBLE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static boolean isSmbLike(String type) {
        return "smb".equals(type) || "internal".equals(type) || "usb".equals(type);
    }

    @Nullable
    private static String optNullableString(JSONObject o, String key) {
        return o == null || !o.has(key) || o.isNull(key) ? null : o.optString(key, null);
    }

    // ── Messages and busy state ────────────────────────────────────────
    private void say(String message, boolean isError) {
        showMessage(message, isError);
        if (!message.isEmpty()) Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }

    /** "Mounting…" and the like: on the page, no toast. */
    private void sayProgress(String message) {
        showMessage(message, false);
    }

    private void showMessage(String message, boolean isError) {
        handler.removeCallbacks(clearMessage);
        messageView.setText(message);
        messageView.setTextColor(getColor(isError ? R.color.osmium_error : android.R.color.white));
        messageView.setVisibility(message.isEmpty() ? View.GONE : View.VISIBLE);
        if (!message.isEmpty()) handler.postDelayed(clearMessage, MESSAGE_CLEAR_MS);
    }

    private void setBusy(boolean value) {
        busy = value;
        progressBar.setVisibility(value || wizBusy ? View.VISIBLE : View.GONE);
        // Buttons follow the busy flag.
        renderActiveList();
        renderDisks();
        renderPlaylist();
    }

    // ── Menu ───────────────────────────────────────────────────────────
    private void renderMenuPage() {
        View active = addMenuRow(content, R.drawable.library_music, getString(R.string.sources_active), null,
                v -> go("active"));
        menuActiveSub = active.findViewById(R.id.sources_row_subtitle);
        addMenuRow(content, R.drawable.ic_add, getString(R.string.sources_add_source),
                getString(R.string.sources_add_source_hint), v -> go("add"));
        menuPlaylistRow = addMenuRow(content, R.drawable.ic_action_playlist,
                getString(R.string.sources_playlistdir_title), null, v -> go("playlist"));
        menuShareRow = addMenuRow(content, R.drawable.folder, getString(R.string.sources_share_title), null,
                v -> go("share"));
        updateMenuSummaries();
    }

    private void updateMenuSummaries() {
        if (menuActiveSub == null) return;
        int count = sources.length();
        menuActiveSub.setText(count > 0
                ? getString(R.string.sources_count_summary, String.valueOf(count))
                : getString(R.string.sources_none_summary));
        menuActiveSub.setVisibility(View.VISIBLE);

        // Hidden on an appliance that predates the endpoint behind them.
        menuPlaylistRow.setVisibility(playlistSupported ? View.VISIBLE : View.GONE);
        setRowSubtitle(menuPlaylistRow, playlistdir.isEmpty()
                ? getString(R.string.sources_playlistdir_unset) : playlistdir);
        menuShareRow.setVisibility(smbCard != null ? View.VISIBLE : View.GONE);
        int shares = shares().length();
        setRowSubtitle(menuShareRow, shares > 0
                ? getString(R.string.sources_share_count, String.valueOf(shares))
                : getString(R.string.sources_share_none));
    }

    // ── Active sources + USB needing attention ─────────────────────────
    private void loadSources(@Nullable Runnable after) {
        api.list(new Cb() {
            @Override
            void ok(JSONObject body) {
                JSONArray list = body.optJSONArray("sources");
                if (list != null) {
                    String json = list.toString();
                    if (!json.equals(sourcesJson)) {
                        sources = list;
                        sourcesJson = json;
                        renderActiveList();
                        updateMenuSummaries();
                    }
                }
                if (after != null) after.run();
            }

            @Override
            void fail(String message) {
                // A missed poll is not worth a message; the next one retries.
                if (after != null) after.run();
            }
        });
    }

    private void loadUsb() {
        api.usbList(new Cb() {
            @Override
            void ok(JSONObject body) {
                JSONArray list = body.optJSONArray("disks");
                if (list == null) return;
                String json = list.toString();
                if (json.equals(usbJson)) return;
                usb = list;
                usbJson = json;
                renderActiveList();
            }

            @Override
            void fail(String message) {
            }
        });
    }

    /** Every edit applies itself on the appliance, so a successful one just refreshes. */
    private void changed() {
        loadSources(null);
        loadSmbCard();
    }

    private String sourceTag(JSONObject s) {
        switch (SourcesApi.str(s, "type")) {
            case "smb":
                return getString(s.optBoolean("rw", false) ? R.string.sources_smb_tag_rw : R.string.sources_smb_tag);
            case "internal":
                return getString(R.string.sources_internal_tag);
            case "usb":
                return getString(R.string.sources_usb_tag);
            default:
                return getString(R.string.sources_local_tag);
        }
    }

    private static String sourceSub(JSONObject s) {
        String type = SourcesApi.str(s, "type");
        String subpath = SourcesApi.str(s, "subpath");
        String mountpoint = SourcesApi.str(s, "mountpoint");
        if ("smb".equals(type)) {
            return "//" + SourcesApi.str(s, "server") + "/" + SourcesApi.str(s, "share") + " → " + mountpoint
                    + (subpath.isEmpty() ? "" : "/" + subpath);
        }
        if ("internal".equals(type) || "usb".equals(type)) {
            return mountpoint + (subpath.isEmpty() ? "" : "/" + subpath);
        }
        return SourcesApi.str(s, "path");
    }

    private static boolean sourceOk(JSONObject s) {
        return isSmbLike(SourcesApi.str(s, "type")) ? s.optBoolean("mounted", false) : s.optBoolean("exists", false);
    }

    private void renderActiveList() {
        if (activeList == null) return;
        activeList.removeAllViews();
        LayoutInflater inflater = LayoutInflater.from(this);
        if (sources.length() == 0) {
            addText(activeList, getString(R.string.sources_none), R.color.hifiSilver);
        }
        for (int i = 0; i < sources.length(); i++) {
            JSONObject s = sources.optJSONObject(i);
            if (s == null) continue;
            String id = SourcesApi.str(s, "id");
            String type = SourcesApi.str(s, "type");
            View row = inflater.inflate(R.layout.sources_source_row, activeList, false);
            ((TextView) row.findViewById(R.id.sources_source_name)).setText(s.optString("name", id));
            ((TextView) row.findViewById(R.id.sources_source_tag)).setText(sourceTag(s));
            TextView sub = row.findViewById(R.id.sources_source_sub);
            sub.setText(sourceSub(s));
            sub.setTextColor(getColor(sourceOk(s) ? R.color.hifiSilver : R.color.osmium_error));

            JSONObject usage = s.optJSONObject("usage");
            if (usage != null) {
                TextView usageView = row.findViewById(R.id.sources_source_usage);
                usageView.setText(getString(R.string.sources_free_of,
                        SourcesFormat.bytes(this, usage.opt("free")), SourcesFormat.bytes(this, usage.opt("total"))));
                usageView.setVisibility(View.VISIBLE);
            }
            if (s.optBoolean("pending_activation", false)) {
                row.findViewById(R.id.sources_source_pending).setVisibility(View.VISIBLE);
            }

            if ("smb".equals(type)) {
                boolean rw = s.optBoolean("rw", false);
                MaterialButton rwButton = row.findViewById(R.id.sources_source_rw);
                rwButton.setText(rw ? R.string.sources_smb_make_ro : R.string.sources_smb_make_rw);
                rwButton.setEnabled(!busy);
                rwButton.setVisibility(View.VISIBLE);
                rwButton.setOnClickListener(v -> setSmbRw(id, !rw));
            }
            if (isSmbLike(type)) {
                MaterialButton subpathButton = row.findViewById(R.id.sources_source_subpath);
                subpathButton.setEnabled(!busy && s.optBoolean("mounted", false));
                subpathButton.setVisibility(View.VISIBLE);
                subpathButton.setOnClickListener(v -> {
                    if (id.equals(browsingId)) {
                        closeBrowse();
                    } else {
                        openBrowse(s);
                    }
                });
            }
            row.findViewById(R.id.sources_source_remove)
                    .setOnClickListener(v -> confirmRemove(id, s.optString("name", id)));

            if (id.equals(browsingId)) {
                ViewGroup holder = row.findViewById(R.id.sources_source_browse);
                holder.setVisibility(View.VISIBLE);
                renderBrowseCard(holder);
            }
            activeList.addView(row);
        }

        // USB devices needing attention: healthy drives are adopted on their
        // own (sources_server.py's usb_sync()) and show up above instead.
        if (usb.length() > 0) {
            View divider = new View(this);
            divider.setBackgroundColor(getColor(R.color.hifiLightGray));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1));
            lp.setMargins(0, dp(18), 0, dp(8));
            activeList.addView(divider, lp);
            addText(activeList, getString(R.string.sources_usb_attention), android.R.color.white);
            for (int i = 0; i < usb.length(); i++) {
                JSONObject dk = usb.optJSONObject(i);
                if (dk == null) continue;
                View row = inflater.inflate(R.layout.sources_usb_row, activeList, false);
                String label = SourcesApi.str(dk, "label");
                ((TextView) row.findViewById(R.id.sources_usb_label))
                        .setText(label.isEmpty() || dk.isNull("label") ? getString(R.string.sources_usb_fallback) : label);
                StringBuilder tag = new StringBuilder(getString(R.string.sources_usb_tag));
                String fstype = optNullableString(dk, "fstype");
                if (fstype != null && !fstype.isEmpty()) tag.append(' ').append(fstype);
                String size = SourcesFormat.size(this, dk.opt("size"));
                if (!size.isEmpty()) tag.append(" · ").append(size);
                ((TextView) row.findViewById(R.id.sources_usb_tag)).setText(tag);
                boolean needsFormat = dk.optBoolean("needs_format", false);
                String error = optNullableString(dk, "error");
                ((TextView) row.findViewById(R.id.sources_usb_error)).setText(needsFormat
                        ? getString(R.string.sources_usb_needs_format)
                        : getString(R.string.sources_usb_mount_error) + ": " + (error != null ? error : ""));
                if (!needsFormat) {
                    String device = optNullableString(dk, "path");
                    MaterialButton retry = row.findViewById(R.id.sources_usb_retry);
                    retry.setVisibility(View.VISIBLE);
                    retry.setEnabled(!busy && device != null && !device.isEmpty());
                    retry.setOnClickListener(v -> retryUsb(device));
                }
                activeList.addView(row);
            }
        }
    }

    private void confirmRemove(String id, String name) {
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.sources_remove)
                .setMessage(getString(R.string.sources_remove_confirm, name))
                .setNegativeButton(R.string.sources_common_cancel, null)
                .setPositiveButton(R.string.sources_remove, (d, w) -> removeSource(id))
                .show();
    }

    private void removeSource(String id) {
        api.remove(id, new Cb() {
            @Override
            void ok(JSONObject body) {
                if (SourcesApi.failed(body)) {
                    say(SourcesApi.message(body, getString(R.string.sources_common_error)), true);
                }
                if (id.equals(browsingId)) browsingId = null;
                changed();
            }
        });
    }

    private void setSmbRw(String id, boolean rw) {
        if (busy) return;
        setBusy(true);
        api.setRw(id, rw, new Cb() {
            @Override
            void ok(JSONObject body) {
                setBusy(false);
                boolean failed = SourcesApi.failed(body);
                say(SourcesApi.message(body, getString(failed ? R.string.sources_common_error : R.string.sources_mounted)),
                        failed);
                if (!failed) loadSources(null);
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    private void retryUsb(String device) {
        if (busy || device == null) return;
        setBusy(true);
        sayProgress(getString(R.string.sources_internal_adopting));
        api.usbAdopt(device, new Cb() {
            @Override
            void ok(JSONObject body) {
                setBusy(false);
                boolean failed = SourcesApi.failed(body);
                say(failed ? SourcesApi.message(body, getString(R.string.sources_common_error))
                        : getString(R.string.sources_internal_adopted), failed);
                if (!failed) {
                    loadUsb();
                    changed();
                }
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    // ── Subfolder picker (smb/internal/usb only) ───────────────────────
    // Narrows a source to a subfolder of its mount, through sources_server.py's
    // api_browse_subpath()/api_set_subpath().
    private void openBrowse(JSONObject s) {
        browsingId = SourcesApi.str(s, "id");
        browsePath = SourcesApi.str(s, "subpath");
        loadBrowse();
    }

    private void closeBrowse() {
        browsingId = null;
        renderActiveList();
    }

    private void loadBrowse() {
        String id = browsingId;
        if (id == null) return;
        browseBusy = true;
        renderActiveList();
        api.browse(id, browsePath, new Cb() {
            @Override
            void ok(JSONObject body) {
                if (!id.equals(browsingId)) return;
                browseBusy = false;
                if (SourcesApi.failed(body) || !body.has("dirs")) {
                    say(SourcesApi.message(body, getString(R.string.sources_common_error)), true);
                    browsingId = null;
                } else {
                    JSONArray dirs = body.optJSONArray("dirs");
                    browseDirs = dirs != null ? dirs : new JSONArray();
                    browseParent = optNullableString(body, "parent");
                }
                renderActiveList();
            }

            @Override
            void fail(String message) {
                if (!id.equals(browsingId)) return;
                browseBusy = false;
                browsingId = null;
                renderActiveList();
                super.fail(message);
            }
        });
    }

    private void renderBrowseCard(ViewGroup holder) {
        View card = LayoutInflater.from(this).inflate(R.layout.sources_browse_card, holder, false);
        holder.addView(card);
        ((TextView) card.findViewById(R.id.sources_browse_path)).setText("/" + browsePath);
        card.findViewById(R.id.sources_browse_close).setOnClickListener(v -> closeBrowse());
        card.findViewById(R.id.sources_browse_loading).setVisibility(browseBusy ? View.VISIBLE : View.GONE);
        card.findViewById(R.id.sources_browse_body).setVisibility(browseBusy ? View.GONE : View.VISIBLE);
        if (browseBusy) return;

        Button up = card.findViewById(R.id.sources_browse_up);
        up.setEnabled(browseParent != null);
        up.setOnClickListener(v -> {
            if (browseParent == null) return;
            browsePath = browseParent;
            loadBrowse();
        });
        Button useHere = card.findViewById(R.id.sources_browse_use_here);
        useHere.setEnabled(!busy);
        useHere.setOnClickListener(v -> useBrowsePath(browsePath));
        Button useRoot = card.findViewById(R.id.sources_browse_use_root);
        useRoot.setEnabled(!busy && !browsePath.isEmpty());
        useRoot.setOnClickListener(v -> useBrowsePath(""));

        card.findViewById(R.id.sources_browse_empty)
                .setVisibility(browseDirs.length() == 0 ? View.VISIBLE : View.GONE);
        LinearLayout dirsView = card.findViewById(R.id.sources_browse_dirs);
        LayoutInflater inflater = LayoutInflater.from(this);
        for (int i = 0; i < browseDirs.length(); i++) {
            String name = browseDirs.optString(i, "");
            if (name.isEmpty()) continue;
            View row = inflater.inflate(R.layout.sources_folder_row, dirsView, false);
            ((TextView) row.findViewById(R.id.sources_folder_name)).setText(name);
            row.setOnClickListener(v -> {
                browsePath = browsePath.isEmpty() ? name : browsePath + "/" + name;
                loadBrowse();
            });
            dirsView.addView(row);
        }
    }

    private void useBrowsePath(String subpath) {
        String id = browsingId;
        if (busy || id == null) return;
        setBusy(true);
        api.setSubpath(id, subpath, new Cb() {
            @Override
            void ok(JSONObject body) {
                boolean failed = SourcesApi.failed(body);
                if (!failed) browsingId = null;
                setBusy(false);
                say(SourcesApi.message(body, getString(failed ? R.string.sources_common_error
                        : R.string.sources_subpath_saved)), failed);
                if (!failed) loadSources(null);
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    // ── Add a local folder (optionally shared on the network) ──────────
    private void addLocal(String path, boolean samba) {
        if (busy || path == null || path.isEmpty()) return;
        setBusy(true);
        api.addLocal(path, samba, new Cb() {
            @Override
            void ok(JSONObject body) {
                setBusy(false);
                boolean failed = SourcesApi.failed(body);
                say(failed ? SourcesApi.message(body, getString(R.string.sources_common_error))
                        : getString(R.string.sources_added), failed);
                if (!failed) changed();
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    // ── Guided "add a network folder" ──────────────────────────────────
    // The appliance looks for file servers on the LAN and reads back what each
    // one shares, so this is a list to pick from; typing it in survives as the
    // fallback. Username and password are asked in a dialog, only once the
    // device (or the folder) turns out to want them.
    private void renderWizardPage() {
        wizRoot = LayoutInflater.from(this).inflate(R.layout.sources_smb_wizard, content, false);
        content.addView(wizRoot);
        View w = wizRoot;

        w.findViewById(R.id.sources_wiz_search_again).setOnClickListener(v -> wizScan());
        w.findViewById(R.id.sources_wiz_type_host).setOnClickListener(v -> {
            wizManual = true;
            wizStopScan();
            renderWizard();
        });
        EditText hostField = w.findViewById(R.id.sources_wiz_host_field);
        hostField.addTextChangedListener(new TextChanged(() -> {
            wizHost = hostField.getText().toString();
            w.findViewById(R.id.sources_wiz_host_continue).setEnabled(!wizHost.trim().isEmpty());
        }));
        w.findViewById(R.id.sources_wiz_host_continue).setOnClickListener(v -> {
            String host = wizHost.trim();
            if (!host.isEmpty()) wizPickHost(host, "");
        });
        w.findViewById(R.id.sources_wiz_manual_search).setOnClickListener(v -> wizScan());

        w.findViewById(R.id.sources_wiz_change_user).setOnClickListener(v -> wizChangeUser());
        w.findViewById(R.id.sources_wiz_need_password).setOnClickListener(v -> wizChangeUser());
        w.findViewById(R.id.sources_wiz_type_share).setOnClickListener(v -> {
            wizCanList = false;
            renderWizard();
        });
        EditText shareField = w.findViewById(R.id.sources_wiz_share_field);
        shareField.addTextChangedListener(new TextChanged(() -> {
            wizShare = shareField.getText().toString();
            w.findViewById(R.id.sources_wiz_share_continue).setEnabled(!wizShare.trim().isEmpty());
        }));
        w.findViewById(R.id.sources_wiz_share_continue).setOnClickListener(v -> {
            if (wizShare.trim().isEmpty()) return;
            wizShare = wizShare.trim();
            wizStep = 2;
            renderWizard();
        });

        SwitchMaterial rwSwitch = w.findViewById(R.id.sources_wiz_rw);
        rwSwitch.setOnCheckedChangeListener((b, checked) -> wizRw = checked);
        w.findViewById(R.id.sources_wiz_add).setOnClickListener(v -> wizAdd());

        w.findViewById(R.id.sources_wiz_detail_toggle).setOnClickListener(v -> {
            wizDetailOpen = !wizDetailOpen;
            renderWizard();
        });
        w.findViewById(R.id.sources_wiz_back).setOnClickListener(v -> {
            if (wizBusy || wizStep == 0) return;
            wizStep--;
            wizErr = "";
            renderWizard();
            // Back on the device list with a scan still under way: follow it again.
            if (wizStep == 0 && !wizManual && "running".equals(scanState) && !scanPolling) {
                scanPolling = true;
                wizPoll();
            }
        });
        w.findViewById(R.id.sources_wiz_start_over).setOnClickListener(v -> {
            wizReset();
            wizScan();
        });
        renderWizard();
    }

    private String wizDeviceName() {
        return wizName.isEmpty() ? wizHost : wizName;
    }

    private void renderWizard() {
        View w = wizRoot;
        if (w == null) return;

        // 1. which device
        boolean scanStep = wizStep == 0 && !wizManual;
        w.findViewById(R.id.sources_wiz_step_scan).setVisibility(scanStep ? View.VISIBLE : View.GONE);
        w.findViewById(R.id.sources_wiz_step_manual)
                .setVisibility(wizStep == 0 && wizManual ? View.VISIBLE : View.GONE);
        if (scanStep) {
            boolean running = "running".equals(scanState);
            TextView searching = w.findViewById(R.id.sources_wiz_searching);
            searching.setVisibility(running ? View.VISIBLE : View.GONE);
            searching.setText(getString(R.string.sources_searching_progress,
                    getString(R.string.sources_wiz_searching), String.valueOf(scanProgress)));
            LinearLayout hosts = w.findViewById(R.id.sources_wiz_hosts);
            // Rebuilt only when the list changed: a row replaced under the
            // finger every 900 ms would swallow the tap.
            String hostsJson = scanHosts.toString();
            boolean rebuild = !hostsJson.equals(hosts.getTag());
            if (rebuild) {
                hosts.setTag(hostsJson);
                hosts.removeAllViews();
            }
            for (int i = 0; rebuild && i < scanHosts.length(); i++) {
                JSONObject h = scanHosts.optJSONObject(i);
                if (h == null) continue;
                String ip = SourcesApi.str(h, "ip");
                String name = optNullableString(h, "name");
                boolean named = name != null && !name.isEmpty();
                addMenuRow(hosts, 0, named ? name : ip, named ? ip : null,
                        v -> wizPickHost(ip, named ? name : ""));
            }
            w.findViewById(R.id.sources_wiz_nothing)
                    .setVisibility(scanHosts.length() == 0 && !running ? View.VISIBLE : View.GONE);
            w.findViewById(R.id.sources_wiz_search_again).setEnabled(!running);
        } else if (wizStep == 0) {
            EditText hostField = w.findViewById(R.id.sources_wiz_host_field);
            if (!hostField.getText().toString().equals(wizHost)) hostField.setText(wizHost);
            w.findViewById(R.id.sources_wiz_host_continue).setEnabled(!wizHost.trim().isEmpty());
        }

        // 2. which shared folder
        w.findViewById(R.id.sources_wiz_step_share).setVisibility(wizStep == 1 ? View.VISIBLE : View.GONE);
        if (wizStep == 1) {
            ((TextView) w.findViewById(R.id.sources_wiz_on_device))
                    .setText(getString(R.string.sources_wiz_on_device, wizDeviceName()));
            w.findViewById(R.id.sources_wiz_user_row).setVisibility(wizUser.isEmpty() ? View.GONE : View.VISIBLE);
            ((TextView) w.findViewById(R.id.sources_wiz_user_text))
                    .setText(getString(R.string.sources_wiz_user_label) + ": " + wizUser);
            w.findViewById(R.id.sources_wiz_change_user).setEnabled(!wizBusy);
            w.findViewById(R.id.sources_wiz_loading_shares).setVisibility(wizBusy ? View.VISIBLE : View.GONE);

            boolean typeShare = !wizBusy && !wizCanList;
            w.findViewById(R.id.sources_wiz_share_manual).setVisibility(typeShare ? View.VISIBLE : View.GONE);
            if (typeShare) {
                EditText shareField = w.findViewById(R.id.sources_wiz_share_field);
                if (!shareField.getText().toString().equals(wizShare)) shareField.setText(wizShare);
                String hint = getString(R.string.sources_wiz_type_share_hint);
                ((TextView) w.findViewById(R.id.sources_wiz_share_hint)).setText(wizNoClient
                        ? getString(R.string.sources_wiz_no_client_hint) + " " + hint : hint);
                w.findViewById(R.id.sources_wiz_share_continue).setEnabled(!wizShare.trim().isEmpty());
            }

            boolean list = !wizBusy && wizCanList;
            w.findViewById(R.id.sources_wiz_share_list).setVisibility(list ? View.VISIBLE : View.GONE);
            if (list) {
                LinearLayout shares = w.findViewById(R.id.sources_wiz_shares);
                shares.removeAllViews();
                for (int i = 0; i < wizShares.length(); i++) {
                    JSONObject sh = wizShares.optJSONObject(i);
                    if (sh == null) continue;
                    String name = SourcesApi.str(sh, "name");
                    addMenuRow(shares, 0, name, optNullableString(sh, "comment"), v -> wizPickShare(name));
                }
                w.findViewById(R.id.sources_wiz_no_shares)
                        .setVisibility(wizShares.length() == 0 && !wizNeedsAuth ? View.VISIBLE : View.GONE);
                View needPassword = w.findViewById(R.id.sources_wiz_need_password);
                needPassword.setVisibility(wizUser.isEmpty() ? View.VISIBLE : View.GONE);
                needPassword.setEnabled(!wizBusy);
            }
        }

        // 3. confirm
        w.findViewById(R.id.sources_wiz_step_confirm).setVisibility(wizStep == 2 ? View.VISIBLE : View.GONE);
        if (wizStep == 2) {
            StringBuilder summary = new StringBuilder()
                    .append(getString(R.string.sources_wiz_device)).append(": ").append(wizDeviceName())
                    .append('\n').append(getString(R.string.sources_wiz_folder)).append(": ").append(wizShare);
            if (!wizUser.isEmpty()) {
                summary.append('\n').append(getString(R.string.sources_wiz_user_label)).append(": ").append(wizUser);
            }
            ((TextView) w.findViewById(R.id.sources_wiz_summary)).setText(summary);
            ((SwitchMaterial) w.findViewById(R.id.sources_wiz_rw)).setChecked(wizRw);
            w.findViewById(R.id.sources_wiz_add).setEnabled(!wizBusy);
        }

        // What went wrong, in words; the raw tool output one tap away.
        w.findViewById(R.id.sources_wiz_error_block).setVisibility(wizErr.isEmpty() ? View.GONE : View.VISIBLE);
        ((TextView) w.findViewById(R.id.sources_wiz_error)).setText(wizErr);
        MaterialButton detailToggle = w.findViewById(R.id.sources_wiz_detail_toggle);
        detailToggle.setVisibility(wizDetail.isEmpty() ? View.GONE : View.VISIBLE);
        detailToggle.setText(wizDetailOpen ? R.string.sources_wiz_hide_detail : R.string.sources_wiz_show_detail);
        TextView detail = w.findViewById(R.id.sources_wiz_detail);
        detail.setText(wizDetail);
        detail.setVisibility(wizDetailOpen && !wizDetail.isEmpty() ? View.VISIBLE : View.GONE);

        w.findViewById(R.id.sources_wiz_nav).setVisibility(wizStep > 0 ? View.VISIBLE : View.GONE);
        w.findViewById(R.id.sources_wiz_back).setEnabled(!wizBusy);

        progressBar.setVisibility(busy || wizBusy ? View.VISIBLE : View.GONE);
    }

    private void wizStopScan() {
        scanPolling = false;
        handler.removeCallbacks(scanPoll);
    }

    private void wizReset() {
        wizStopScan();
        wizToken++;
        wizStep = 0;
        wizManual = false;
        wizHost = "";
        wizName = "";
        wizShare = "";
        wizUser = "";
        wizPass = "";
        wizRw = false;
        wizBusy = false;
        wizErr = "";
        wizDetail = "";
        wizDetailOpen = false;
        wizNeedsAuth = false;
        wizCanList = true;
        wizNoClient = false;
        scanState = "";
        scanProgress = 0;
        scanHosts = new JSONArray();
        wizShares = new JSONArray();
        if (loginDialog != null && loginDialog.isShowing()) loginDialog.dismiss();
        renderWizard();
    }

    private void wizFail(@Nullable JSONObject body, int fallbackRes) {
        wizErr = SourcesApi.message(body, getString(fallbackRes));
        wizDetail = body != null ? SourcesApi.str(body, "detail") : "";
        wizDetailOpen = false;
    }

    private void wizScan() {
        wizManual = false;
        wizErr = "";
        wizDetail = "";
        wizStopScan();
        scanState = "running";
        scanProgress = 0;
        scanHosts = new JSONArray();
        renderWizard();
        int token = wizToken;
        api.smbDiscoverStart(new Cb() {
            @Override
            void ok(JSONObject body) {
                if (token != wizToken) return;
                scanPolling = true;
                wizPoll();
            }

            @Override
            void fail(String message) {
                if (token != wizToken) return;
                scanPolling = true;
                wizPoll();
            }
        });
    }

    private void wizPoll() {
        int token = wizToken;
        api.smbDiscoverStatus(new Cb() {
            @Override
            void ok(JSONObject body) {
                if (token != wizToken || !scanPolling) return;
                if (SourcesApi.failed(body) || !body.has("state")) {
                    // No scan on this appliance (or the pairing was refused):
                    // end the search so typing the address stays possible.
                    wizStopScan();
                    scanState = "";
                    if (body != null && body.has("message")) wizFail(body, R.string.sources_common_error);
                    renderWizard();
                    return;
                }
                scanState = SourcesApi.str(body, "state");
                scanProgress = body.optInt("progress", 0);
                JSONArray hosts = body.optJSONArray("hosts");
                scanHosts = hosts != null ? hosts : new JSONArray();
                // Without smbclient the shares cannot be listed, so the flow
                // falls back to typing the folder name.
                JSONObject tools = body.optJSONObject("tools");
                if (tools != null && tools.has("shares") && !tools.optBoolean("shares", true)) {
                    wizCanList = false;
                    wizNoClient = true;
                }
                if ("running".equals(scanState)) {
                    handler.postDelayed(scanPoll, SCAN_POLL_MS);
                } else {
                    wizStopScan();
                }
                renderWizard();
            }

            @Override
            void fail(String message) {
                if (token != wizToken || !scanPolling) return;
                wizStopScan();
                scanState = "";
                renderWizard();
            }
        });
    }

    private void wizPickHost(String ip, String name) {
        wizStopScan();
        wizHost = ip;
        wizName = name.isEmpty() ? ip : name;
        wizShare = "";
        wizShares = new JSONArray();
        wizNeedsAuth = false;
        wizErr = "";
        wizDetail = "";
        wizStep = 1;
        renderWizard();
        if (wizCanList) wizLoadShares();
    }

    /** Asks for a login. `refused`: the previous attempt was turned down. `retry` runs with the new login. */
    private void wizAskAuth(boolean refused, @Nullable Runnable retry) {
        if (destroyed || isFinishing()) return;
        if (loginDialog != null && loginDialog.isShowing()) loginDialog.dismiss();
        View view = LayoutInflater.from(this).inflate(R.layout.sources_dialog_login, null);
        EditText userField = view.findViewById(R.id.sources_login_user);
        EditText passField = view.findViewById(R.id.sources_login_pass);
        TextView errorView = view.findViewById(R.id.sources_login_error);
        userField.setText(wizUser);
        if (refused) {
            errorView.setText(R.string.sources_wiz_wrong_password);
            errorView.setVisibility(View.VISIBLE);
        }

        AlertDialog dialog = new MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.sources_wiz_sign_in_to, wizDeviceName()))
                .setView(view)
                .setNegativeButton(R.string.sources_common_cancel, null)
                .setPositiveButton(R.string.sources_wiz_sign_in, (d, which) -> {
                    String user = userField.getText().toString().trim();
                    if (user.isEmpty()) return;
                    wizUser = user;
                    wizPass = passField.getText().toString();
                    wizNeedsAuth = true;
                    renderWizard();
                    if (retry != null) retry.run();
                })
                .create();
        Runnable updateButton = () -> {
            Button positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            if (positive != null) positive.setEnabled(!userField.getText().toString().trim().isEmpty());
        };
        userField.addTextChangedListener(new TextChanged(() -> {
            errorView.setVisibility(View.GONE);
            updateButton.run();
        }));
        passField.addTextChangedListener(new TextChanged(() -> errorView.setVisibility(View.GONE)));
        passField.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId != EditorInfo.IME_ACTION_DONE) return false;
            Button positive = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            if (positive != null && positive.isEnabled()) positive.performClick();
            return true;
        });
        dialog.setOnShowListener(d -> {
            updateButton.run();
            (wizUser.isEmpty() ? userField : passField).requestFocus();
        });
        if (dialog.getWindow() != null) {
            dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
        }
        loginDialog = dialog;
        dialog.show();
    }

    private void wizChangeUser() {
        // With no list yet the login is for reading it; otherwise the next
        // folder picked uses it.
        wizAskAuth(false, () -> {
            if (wizCanList && wizShares.length() == 0) wizLoadShares();
        });
    }

    private void wizLoadShares() {
        wizBusy = true;
        wizErr = "";
        wizDetail = "";
        renderWizard();
        boolean tried = !wizUser.isEmpty();
        int token = wizToken;
        api.smbShares(wizHost, wizUser, wizPass, new Cb() {
            @Override
            void ok(JSONObject body) {
                if (token != wizToken) return;
                wizBusy = false;
                if (wizStep != 1) {
                    renderWizard();
                    return;
                }
                if (SourcesApi.failed(body) || !body.has("shares")) {
                    // Wrong password: ask again. Only a real failure falls back
                    // to typing the folder name.
                    if (BAD_CREDENTIALS.equals(SourcesApi.str(body, "code"))) {
                        wizNeedsAuth = true;
                        renderWizard();
                        wizAskAuth(tried, SourcesActivity.this::wizLoadShares);
                        return;
                    }
                    wizFail(body, R.string.sources_wiz_list_failed);
                    wizCanList = false;
                    renderWizard();
                    return;
                }
                wizNeedsAuth = body.optBoolean("needs_auth", false);
                JSONArray shares = body.optJSONArray("shares");
                wizShares = shares != null ? shares : new JSONArray();
                renderWizard();
                // the list itself is behind a login
                if (wizNeedsAuth && wizShares.length() == 0) wizAskAuth(tried, SourcesActivity.this::wizLoadShares);
            }

            @Override
            void fail(String message) {
                if (token != wizToken) return;
                wizBusy = false;
                if (wizStep == 1) {
                    wizFail(null, R.string.sources_wiz_list_failed);
                    wizDetail = message != null ? message : "";
                    wizCanList = false;
                }
                renderWizard();
            }
        });
    }

    private void wizPickShare(String name) {
        wizShare = name;
        wizErr = "";
        wizDetail = "";
        wizBusy = true;
        renderWizard();
        boolean tried = !wizUser.isEmpty();
        int token = wizToken;
        api.smbTest(wizHost, name, wizUser, wizPass, new Cb() {
            @Override
            void ok(JSONObject body) {
                if (token != wizToken) return;
                wizBusy = false;
                if (wizStep != 1) {
                    renderWizard();
                    return;
                }
                if (!SourcesApi.failed(body)) {
                    wizStep = 2;
                    renderWizard();
                    return;
                }
                // A folder that wants a login asks for it right here, not with an
                // error and not at the end as a failed mount.
                if (BAD_CREDENTIALS.equals(SourcesApi.str(body, "code"))) {
                    wizNeedsAuth = true;
                    renderWizard();
                    wizAskAuth(tried, () -> wizPickShare(name));
                    return;
                }
                wizFail(body, R.string.sources_wiz_open_failed);
                renderWizard();
            }

            @Override
            void fail(String message) {
                if (token != wizToken) return;
                wizBusy = false;
                if (wizStep == 1) {
                    wizFail(null, R.string.sources_wiz_open_failed);
                    wizDetail = message != null ? message : "";
                }
                renderWizard();
            }
        });
    }

    private void wizAdd() {
        if (wizBusy || wizHost.isEmpty() || wizShare.isEmpty()) return;
        wizBusy = true;
        wizErr = "";
        wizDetail = "";
        renderWizard();
        sayProgress(getString(R.string.sources_mounting));
        int token = wizToken;
        api.addSmb(wizHost, wizShare, wizUser, wizPass, wizRw, new Cb() {
            @Override
            void ok(JSONObject body) {
                if (token != wizToken) return;
                wizBusy = false;
                if (SourcesApi.failed(body) || !body.has("id")) {
                    if (wizStep == 2 && BAD_CREDENTIALS.equals(SourcesApi.str(body, "code"))) {
                        say("", false);
                        wizStep = 1;
                        wizNeedsAuth = true;
                        renderWizard();
                        wizAskAuth(!wizUser.isEmpty(), () -> wizPickShare(wizShare));
                        return;
                    }
                    wizFail(body, R.string.sources_common_error);
                    renderWizard();
                    say(SourcesApi.message(body, getString(R.string.sources_common_error)), true);
                    return;
                }
                // Mounted but not handed to Lyrion yet (defer_activation): open
                // the new source's subfolder browser so the owner picks the
                // whole share or one folder of it.
                String id = SourcesApi.str(body, "id");
                wizReset();
                loadSources(() -> {
                    loadSmbCard();
                    JSONObject added = null;
                    for (int i = 0; i < sources.length(); i++) {
                        JSONObject s = sources.optJSONObject(i);
                        if (s != null && id.equals(SourcesApi.str(s, "id"))) added = s;
                    }
                    if (added != null) {
                        openPage("active");
                        openBrowse(added);
                    }
                    say(getString(R.string.sources_choose_folder_hint), false);
                });
            }

            @Override
            void fail(String message) {
                if (token != wizToken) return;
                wizBusy = false;
                wizFail(null, R.string.sources_common_error);
                wizDetail = message != null ? message : "";
                renderWizard();
                super.fail(message);
            }
        });
    }

    // ── Internal disks (use existing / format) ─────────────────────────
    // Disks already in use appear under "Active sources"; this list still shows
    // them, without buttons, so the full set of hardware stays legible.
    private void loadInternal() {
        api.internalDisks(new Cb() {
            @Override
            void ok(JSONObject body) {
                JSONArray list = body.optJSONArray("disks");
                if (list == null) return;
                String json = list.toString();
                if (json.equals(disksJson)) return;
                internalDisks = list;
                disksJson = json;
                renderDisks();
            }

            @Override
            void fail(String message) {
            }
        });
    }

    private void renderDisks() {
        if (disksList == null) return;
        disksList.removeAllViews();
        if (internalDisks.length() == 0) {
            addText(disksList, getString(R.string.sources_internal_none), R.color.hifiSilver);
            return;
        }
        LayoutInflater inflater = LayoutInflater.from(this);
        for (int i = 0; i < internalDisks.length(); i++) {
            JSONObject dk = internalDisks.optJSONObject(i);
            if (dk == null) continue;
            View row = inflater.inflate(R.layout.sources_disk_row, disksList, false);
            String model = SourcesApi.str(dk, "model");
            String path = SourcesApi.str(dk, "path");
            ((TextView) row.findViewById(R.id.sources_disk_model)).setText(model.isEmpty() ? path : model);

            boolean adopted = dk.optBoolean("adopted", false);
            StringBuilder badges = new StringBuilder(SourcesFormat.size(this, dk.opt("size")));
            String state = adopted ? getString(R.string.sources_internal_adopted_badge)
                    : dk.optBoolean("has_data", false) ? getString(R.string.sources_internal_has_data) : "";
            if (!state.isEmpty()) badges.append(badges.length() > 0 ? " · " : "").append(state);
            ((TextView) row.findViewById(R.id.sources_disk_badges)).setText(badges);

            StringBuilder sub = new StringBuilder(path);
            String fstype = optNullableString(dk, "fstype");
            if (fstype != null && !fstype.isEmpty()) sub.append(" · ").append(fstype);
            String label = optNullableString(dk, "label");
            if (label != null && !label.isEmpty()) sub.append(" · ").append(label);
            ((TextView) row.findViewById(R.id.sources_disk_sub)).setText(sub);

            List<JSONObject> withFs = new ArrayList<>();
            JSONArray parts = dk.optJSONArray("partitions");
            for (int p = 0; parts != null && p < parts.length(); p++) {
                JSONObject part = parts.optJSONObject(p);
                String fs = optNullableString(part, "fstype");
                if (part != null && fs != null && !fs.isEmpty()) withFs.add(part);
            }

            View actions = row.findViewById(R.id.sources_disk_actions);
            actions.setVisibility(adopted ? View.GONE : View.VISIBLE);
            if (!adopted) {
                if (withFs.size() == 1) {
                    MaterialButton adopt = row.findViewById(R.id.sources_disk_adopt);
                    adopt.setVisibility(View.VISIBLE);
                    adopt.setEnabled(!busy);
                    String device = withFs.get(0).optString("path", "");
                    adopt.setOnClickListener(v -> adoptInternal(device));
                }
                MaterialButton format = row.findViewById(R.id.sources_disk_format);
                format.setEnabled(!busy);
                format.setOnClickListener(v -> openFormat(dk));
            }

            if (!adopted && withFs.size() > 1) {
                LinearLayout partsView = row.findViewById(R.id.sources_disk_partitions);
                partsView.setVisibility(View.VISIBLE);
                for (JSONObject part : withFs) {
                    View partRow = inflater.inflate(R.layout.sources_partition_row, partsView, false);
                    StringBuilder text = new StringBuilder(SourcesApi.str(part, "path"))
                            .append(" · ").append(SourcesApi.str(part, "fstype"));
                    String partLabel = optNullableString(part, "label");
                    if (partLabel != null && !partLabel.isEmpty()) text.append(" · ").append(partLabel);
                    ((TextView) partRow.findViewById(R.id.sources_partition_text)).setText(text);
                    MaterialButton use = partRow.findViewById(R.id.sources_partition_use);
                    use.setEnabled(!busy);
                    String device = SourcesApi.str(part, "path");
                    use.setOnClickListener(v -> adoptInternal(device));
                    partsView.addView(partRow);
                }
            }
            disksList.addView(row);
        }
    }

    private void adoptInternal(String device) {
        if (busy) return;
        setBusy(true);
        sayProgress(getString(R.string.sources_internal_adopting));
        api.internalAdopt(device, new Cb() {
            @Override
            void ok(JSONObject body) {
                setBusy(false);
                boolean failed = SourcesApi.failed(body);
                say(failed ? SourcesApi.message(body, getString(R.string.sources_common_error))
                        : getString(R.string.sources_internal_adopted), failed);
                if (!failed) {
                    loadInternal();
                    changed();
                }
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    private void openFormat(JSONObject disk) {
        if (busy) return;
        if (formatDialog != null) formatDialog.dismiss();
        formatDialog = FormatDiskDialog.show(this, api, disk, () -> {
            loadInternal();
            changed();
        });
    }

    // ── Playlist folder ────────────────────────────────────────────────
    // Where Lyrion saves playlists created from the player. The appliance sets
    // a working default on its own; this is the override.
    private void loadPlaylistdir() {
        api.playlistdirGet(new Cb() {
            @Override
            void ok(JSONObject body) {
                if (SourcesApi.failed(body) || !body.has("path")) {
                    playlistSupported = false;
                } else {
                    playlistSupported = true;
                    playlistdir = SourcesApi.str(body, "path");
                    playlistdirDefault = SourcesApi.str(body, "default");
                }
                updateMenuSummaries();
                renderPlaylist();
            }

            @Override
            void fail(String message) {
                playlistSupported = false;
                updateMenuSummaries();
            }
        });
    }

    private void renderPlaylistPage() {
        playlistPage = LayoutInflater.from(this).inflate(R.layout.sources_playlist_page, content, false);
        content.addView(playlistPage);
        playlistPage.findViewById(R.id.sources_playlist_pick)
                .setOnClickListener(v -> setPlaylistPickerOpen(!playlistPickerOpen));
        playlistPage.findViewById(R.id.sources_playlist_default)
                .setOnClickListener(v -> savePlaylistdir(playlistdirDefault));
        renderPlaylist();
    }

    private void renderPlaylist() {
        if (playlistPage == null) return;
        ((TextView) playlistPage.findViewById(R.id.sources_playlist_path))
                .setText(playlistdir.isEmpty() ? getString(R.string.sources_playlistdir_unset) : playlistdir);
        ((MaterialButton) playlistPage.findViewById(R.id.sources_playlist_pick))
                .setText(playlistPickerOpen ? R.string.sources_common_close : R.string.sources_playlistdir_pick);
        playlistPage.findViewById(R.id.sources_playlist_default).setEnabled(
                !busy && !playlistdirDefault.isEmpty() && !playlistdir.equals(playlistdirDefault));
    }

    private void setPlaylistPickerOpen(boolean open) {
        if (playlistPage == null) return;
        playlistPickerOpen = open;
        ViewGroup holder = playlistPage.findViewById(R.id.sources_playlist_picker);
        detachPicker();
        holder.removeAllViews();
        if (open) {
            // Start from the folder in use, so "somewhere near here" is one tap away.
            picker = new FolderPicker(holder, api, getString(R.string.sources_playlistdir_use), playlistdir,
                    pickerListener(this::savePlaylistdir));
        }
        renderPlaylist();
    }

    private void savePlaylistdir(String path) {
        if (busy || path == null || path.isEmpty()) return;
        setBusy(true);
        api.playlistdirSet(path, new Cb() {
            @Override
            void ok(JSONObject body) {
                setBusy(false);
                boolean failed = SourcesApi.failed(body);
                say(SourcesApi.message(body, getString(failed ? R.string.sources_common_error
                        : R.string.sources_playlistdir_saved)), failed);
                if (!failed) {
                    setPlaylistPickerOpen(false);
                    loadPlaylistdir();
                }
            }

            @Override
            void fail(String message) {
                setBusy(false);
                super.fail(message);
            }
        });
    }

    // ── Shared folders (what this player publishes on the network) ─────
    private void loadSmbCard() {
        api.internalSmb(new Cb() {
            @Override
            void ok(JSONObject body) {
                smbCard = body.has("shares") ? body : null;
                updateMenuSummaries();
                renderShares();
            }

            @Override
            void fail(String message) {
            }
        });
    }

    private JSONArray shares() {
        JSONArray list = smbCard != null ? smbCard.optJSONArray("shares") : null;
        return list != null ? list : new JSONArray();
    }

    private void renderSharePage() {
        sharePage = LayoutInflater.from(this).inflate(R.layout.sources_share_page, content, false);
        content.addView(sharePage);
        sharePage.findViewById(R.id.sources_share_regenerate).setOnClickListener(v -> regenSmb());
        addMenuRow(sharePage.findViewById(R.id.sources_share_local_row), R.drawable.folder,
                getString(R.string.sources_share_local), null, v -> go("local"));
        renderShares();
    }

    private void renderShares() {
        if (sharePage == null) return;
        boolean needUpdate = smbCard != null && !smbCard.optBoolean("installed", true);
        JSONArray shares = shares();
        boolean any = !needUpdate && shares.length() > 0;
        sharePage.findViewById(R.id.sources_share_need_update).setVisibility(needUpdate ? View.VISIBLE : View.GONE);
        sharePage.findViewById(R.id.sources_share_block).setVisibility(any ? View.VISIBLE : View.GONE);
        sharePage.findViewById(R.id.sources_share_none)
                .setVisibility(!needUpdate && !any ? View.VISIBLE : View.GONE);
        if (!any) return;

        // The addresses are what people open this screen for, so they are on
        // screen straight away; Info only adds the step-by-step.
        String host = SmbHowtoDialog.host(smbCard);
        LinearLayout list = sharePage.findViewById(R.id.sources_share_list);
        list.removeAllViews();
        LayoutInflater inflater = LayoutInflater.from(this);
        for (int i = 0; i < shares.length(); i++) {
            JSONObject share = shares.optJSONObject(i);
            if (share == null) continue;
            String name = SourcesApi.str(share, "name");
            View item = inflater.inflate(R.layout.sources_share_item, list, false);
            ((TextView) item.findViewById(R.id.sources_share_name)).setText(name);
            ((TextView) item.findViewById(R.id.sources_share_paths)).setText(
                    getString(R.string.sources_os_windows) + "  " + SmbHowtoDialog.winPath(host, name) + "\n"
                            + getString(R.string.sources_os_macos) + "  " + SmbHowtoDialog.macPath(host, name));
            item.findViewById(R.id.sources_share_info)
                    .setOnClickListener(v -> SmbHowtoDialog.show(this, smbCard, name));
            list.addView(item);
        }

        String alt = SmbHowtoDialog.altHost(smbCard);
        TextView altView = sharePage.findViewById(R.id.sources_share_alt_host);
        altView.setVisibility(alt.isEmpty() ? View.GONE : View.VISIBLE);
        altView.setText(getString(R.string.sources_smb_alt_host_hint, alt));
        ((TextView) sharePage.findViewById(R.id.sources_share_login)).setText(
                getString(R.string.sources_smb_share_user) + ": " + SourcesApi.str(smbCard, "username") + "\n"
                        + getString(R.string.sources_smb_share_pass) + ": " + SourcesApi.str(smbCard, "password"));
    }

    private void regenSmb() {
        api.internalSmbRegenerate(new Cb() {
            @Override
            void ok(JSONObject body) {
                if (SourcesApi.failed(body)) {
                    say(SourcesApi.message(body, getString(R.string.sources_common_error)), true);
                }
                loadSmbCard();
            }
        });
    }
}
