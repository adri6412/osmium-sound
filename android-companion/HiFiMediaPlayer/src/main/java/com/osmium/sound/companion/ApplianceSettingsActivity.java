package com.osmium.sound.companion;

import android.os.Build;
import android.os.Bundle;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ProgressBar;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.annotation.LayoutRes;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;

import org.json.JSONException;
import org.json.JSONObject;

import com.osmium.sound.companion.appliance.ApplianceHttpClient;
import com.osmium.sound.companion.util.ThemeManager;
import com.osmium.sound.companion.widget.ViewUtilities;

/**
 * Shared frame for the appliance settings screens that mirror a section of the
 * web admin's Settings page (Display, Playback, Services, ...): toolbar, a
 * scrolling body, a busy spinner and a message line, plus the request plumbing
 * every one of them repeats — a POST whose failure shows the appliance's own
 * message, and a way to reflect server state in a control without firing its
 * change listener.
 */
public abstract class ApplianceSettingsActivity extends AppCompatActivity {
    private final ThemeManager mThemeManager = new ThemeManager();

    private ProgressBar progressBar;
    private TextView messageView;
    private int busyCount;
    private boolean quiet;

    public interface BodyCallback {
        void onBody(JSONObject body);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mThemeManager.onCreate(this);
        EdgeToEdge.enable(this);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
    }

    /** Inflates `bodyLayout` into the shared frame, titled `title`. Call from onCreate. */
    protected void setUpScreen(@StringRes int title, @LayoutRes int bodyLayout) {
        setContentView(R.layout.appliance_settings_screen);
        Toolbar toolbar = findViewById(R.id.toolbar);
        toolbar.setTitle(title);
        setSupportActionBar(toolbar);
        ViewUtilities.setInsetsListener(toolbar, true, false, false);
        ViewUtilities.setInsetsListener(findViewById(R.id.appliance_container), false, true, false);
        ViewGroup content = findViewById(R.id.appliance_content);
        getLayoutInflater().inflate(bodyLayout, content, true);
        progressBar = findViewById(R.id.appliance_progress);
        messageView = findViewById(R.id.appliance_message);
    }

    protected void setBusy(boolean busy) {
        busyCount = Math.max(0, busyCount + (busy ? 1 : -1));
        progressBar.setVisibility(busyCount > 0 ? View.VISIBLE : View.GONE);
    }

    protected void showMessage(String message) {
        messageView.setText(message);
        if (message != null && !message.isEmpty()) {
            Toast.makeText(this, message, Toast.LENGTH_LONG).show();
        }
    }

    /** True while {@link #quietly} runs: change listeners must ignore the event. */
    protected boolean isQuiet() {
        return quiet;
    }

    /** Runs `r` (typically check()/setChecked()) with listeners told to stay out of it. */
    protected void quietly(Runnable r) {
        boolean was = quiet;
        quiet = true;
        try {
            r.run();
        } finally {
            quiet = was;
        }
    }

    protected static JSONObject json(Object... keyValues) {
        JSONObject o = new JSONObject();
        try {
            for (int i = 0; i + 1 < keyValues.length; i += 2) {
                o.put((String) keyValues[i], keyValues[i + 1]);
            }
        } catch (JSONException ignored) {
        }
        return o;
    }

    /**
     * GET that hands a usable body to `onBody`, or calls `onMissing` when the
     * appliance can't answer it: network failure, or a body without
     * `requiredField` (an older appliance without the route answers 404, a
     * missing/revoked pairing answers 401 — both come back as JSON errors).
     */
    protected void load(String path, String requiredField, BodyCallback onBody, @Nullable Runnable onMissing) {
        ApplianceHttpClient.getJson(path, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (isFinishing()) return;
                if (requiredField != null && !body.has(requiredField)) {
                    if (onMissing != null) onMissing.run();
                    return;
                }
                onBody.onBody(body);
            }

            @Override
            public void onFailure(String message) {
                if (isFinishing()) return;
                if (onMissing != null) onMissing.run();
            }
        });
    }

    /**
     * POST with the spinner up. `onOk` gets the body when the appliance did it;
     * otherwise its own message (or `failRes`) is shown and `onFail` runs, so
     * the caller can put the control back the way it really is.
     */
    protected void post(String path, @Nullable JSONObject payload, @StringRes int failRes,
                        @Nullable BodyCallback onOk, @Nullable Runnable onFail) {
        setBusy(true);
        ApplianceHttpClient.postJson(path, payload, new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (isFinishing()) return;
                setBusy(false);
                if (body.optBoolean("success", true)) {
                    if (onOk != null) onOk.onBody(body);
                } else {
                    showMessage(messageOf(body, getString(failRes)));
                    if (onFail != null) onFail.run();
                }
            }

            @Override
            public void onFailure(String message) {
                if (isFinishing()) return;
                setBusy(false);
                showMessage(getString(failRes) + ": " + message);
                if (onFail != null) onFail.run();
            }
        });
    }

    /** The appliance's own `message`, or `fallback`. */
    protected static String messageOf(JSONObject body, String fallback) {
        String m = body.optString("message", "");
        return m.isEmpty() ? fallback : m;
    }

    /** A radio button carrying `tag`, for option lists built at run time. */
    protected RadioButton addRadio(RadioGroup group, String label, Object tag) {
        RadioButton button = new RadioButton(this);
        button.setId(View.generateViewId());
        button.setText(label);
        button.setTag(tag);
        group.addView(button);
        return button;
    }

    /** Checks the radio button whose tag equals `tag`, without firing listeners. */
    protected void checkByTag(RadioGroup group, Object tag) {
        quietly(() -> {
            for (int i = 0; i < group.getChildCount(); i++) {
                View child = group.getChildAt(i);
                if (child instanceof RadioButton && tag != null && tag.equals(child.getTag())) {
                    group.check(child.getId());
                    return;
                }
            }
            group.clearCheck();
        });
    }

    /** Tag of the checked radio button, or null. */
    @Nullable
    protected static Object checkedTag(RadioGroup group, int checkedId) {
        View checked = group.findViewById(checkedId);
        return checked != null ? checked.getTag() : null;
    }

    @Override
    public void onResume() {
        super.onResume();
        mThemeManager.onResume(this);
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            finish();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }
}
