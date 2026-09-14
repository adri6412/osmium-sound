package com.osmium.sound.companion.sources;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.text.InputFilter;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.RadioGroup;
import android.widget.TextView;

import androidx.appcompat.app.AlertDialog;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputLayout;

import org.json.JSONObject;

import com.osmium.sound.companion.R;
import com.osmium.sound.companion.appliance.ApplianceHttpClient;

/**
 * Format wizard for one internal disk (choose → confirm → progress → done or
 * error), one disk at a time. Mirrors the web admin's SourcesPanel.vue format
 * wizard: the "Format now" button only arms once the disk label has been typed
 * back, and the server double-checks with the disk's own `confirm` fingerprint.
 * The job runs detached on the appliance; its status file is polled every 2 s.
 */
public final class FormatDiskDialog {
    public interface Listener {
        /** The disk was formatted and adopted: refresh the lists. */
        void onFormatted();
    }

    private static final long POLL_MS = 2000;

    private final Context context;
    private final SourcesApi api;
    private final JSONObject disk;
    private final Listener listener;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final AlertDialog dialog;

    private final View stepChoose;
    private final View stepConfirm;
    private final View stepProgress;
    private final View stepResult;
    private final RadioGroup fsGroup;
    private final EditText labelField;
    private final MaterialButton nextButton;
    private final TextView warnBody;
    private final TextInputLayout typedLayout;
    private final EditText typedField;
    private final MaterialButton formatButton;
    private final ProgressBar progressBar;
    private final TextView statusView;
    private final TextView pctView;
    private final TextView resultTitle;
    private final TextView resultText;

    private Runnable pollTask;
    private boolean done;
    private boolean succeeded;

    public static FormatDiskDialog show(Context context, SourcesApi api, JSONObject disk, Listener listener) {
        return new FormatDiskDialog(context, api, disk, listener);
    }

    private FormatDiskDialog(Context context, SourcesApi api, JSONObject disk, Listener listener) {
        this.context = context;
        this.api = api;
        this.disk = disk;
        this.listener = listener;

        View view = LayoutInflater.from(context).inflate(R.layout.sources_dialog_format, null);
        stepChoose = view.findViewById(R.id.sources_format_step_choose);
        stepConfirm = view.findViewById(R.id.sources_format_step_confirm);
        stepProgress = view.findViewById(R.id.sources_format_step_progress);
        stepResult = view.findViewById(R.id.sources_format_step_result);
        fsGroup = view.findViewById(R.id.sources_format_fs);
        labelField = view.findViewById(R.id.sources_format_label);
        nextButton = view.findViewById(R.id.sources_format_next);
        warnBody = view.findViewById(R.id.sources_format_warn_body);
        typedLayout = view.findViewById(R.id.sources_format_typed_layout);
        typedField = view.findViewById(R.id.sources_format_typed);
        formatButton = view.findViewById(R.id.sources_format_now);
        progressBar = view.findViewById(R.id.sources_format_progress);
        statusView = view.findViewById(R.id.sources_format_status);
        pctView = view.findViewById(R.id.sources_format_pct);
        resultTitle = view.findViewById(R.id.sources_format_result_title);
        resultText = view.findViewById(R.id.sources_format_result_text);

        String name = diskName(disk);
        String size = SourcesFormat.size(context, disk.opt("size"));
        ((TextView) view.findViewById(R.id.sources_format_disk))
                .setText(size.isEmpty() ? name : name + " · " + size);

        labelField.setText(context.getString(R.string.sources_default_disk_label));
        // exFAT labels stop at 11 characters, ext4 at 16.
        fsGroup.setOnCheckedChangeListener((group, checkedId) -> applyLabelLimit());
        labelField.addTextChangedListener(new TextChanged(this::updateChooseButtons));
        typedField.addTextChangedListener(new TextChanged(this::updateConfirmButton));

        view.findViewById(R.id.sources_format_cancel).setOnClickListener(v -> close());
        nextButton.setOnClickListener(v -> toConfirm());
        view.findViewById(R.id.sources_format_back).setOnClickListener(v -> showStep(stepChoose));
        formatButton.setOnClickListener(v -> startFormat());
        view.findViewById(R.id.sources_format_close).setOnClickListener(v -> close());

        dialog = new MaterialAlertDialogBuilder(context)
                .setView(view)
                .setCancelable(false)
                .create();
        dialog.setOnDismissListener(d -> stopPolling());
        dialog.show();
        updateChooseButtons();
    }

    static String diskName(JSONObject disk) {
        String model = SourcesApi.str(disk, "model");
        return model.isEmpty() ? SourcesApi.str(disk, "path") : model;
    }

    private String fs() {
        return fsGroup.getCheckedRadioButtonId() == R.id.sources_format_fs_exfat ? "exfat" : "ext4";
    }

    private String label() {
        return labelField.getText().toString().trim();
    }

    private void applyLabelLimit() {
        int max = "exfat".equals(fs()) ? 11 : 16;
        labelField.setFilters(new InputFilter[]{new InputFilter.LengthFilter(max)});
        String text = labelField.getText().toString();
        if (text.length() > max) labelField.setText(text.substring(0, max));
    }

    private void updateChooseButtons() {
        nextButton.setEnabled(!label().isEmpty());
    }

    private void updateConfirmButton() {
        String label = label();
        formatButton.setEnabled(!label.isEmpty() && typedField.getText().toString().trim().equals(label));
    }

    private void toConfirm() {
        if (label().isEmpty()) return;
        String size = SourcesFormat.size(context, disk.opt("size"));
        warnBody.setText(context.getString(R.string.sources_warn_body,
                diskName(disk), size, SourcesApi.str(disk, "path")));
        typedLayout.setHint(context.getString(R.string.sources_type_to_confirm, label()));
        typedField.setText("");
        updateConfirmButton();
        showStep(stepConfirm);
    }

    private void showStep(View step) {
        stepChoose.setVisibility(step == stepChoose ? View.VISIBLE : View.GONE);
        stepConfirm.setVisibility(step == stepConfirm ? View.VISIBLE : View.GONE);
        stepProgress.setVisibility(step == stepProgress ? View.VISIBLE : View.GONE);
        stepResult.setVisibility(step == stepResult ? View.VISIBLE : View.GONE);
    }

    private void startFormat() {
        showStep(stepProgress);
        progressBar.setProgress(0);
        statusView.setText(R.string.sources_phase_preparing);
        pctView.setText(context.getString(R.string.sources_percent, "0"));
        api.internalFormat(SourcesApi.str(disk, "path"), fs(), label(), SourcesApi.str(disk, "confirm"),
                new ApplianceHttpClient.JsonCallback() {
                    @Override
                    public void onSuccess(JSONObject body) {
                        if (done) return;
                        if (SourcesApi.failed(body)) {
                            showError(SourcesApi.message(body, context.getString(R.string.sources_common_error)));
                            return;
                        }
                        poll();
                    }

                    @Override
                    public void onFailure(String message) {
                        if (done) return;
                        showError(context.getString(R.string.sources_common_error) + ": " + message);
                    }
                });
    }

    private void poll() {
        pollTask = () -> api.internalFormatStatus(new ApplianceHttpClient.JsonCallback() {
            @Override
            public void onSuccess(JSONObject body) {
                if (done) return;
                String state = SourcesApi.str(body, "state");
                if ("done".equals(state)) {
                    succeeded = true;
                    showResult(context.getString(R.string.sources_done_adopted),
                            context.getString(R.string.sources_done_hint), false);
                    return;
                }
                if ("error".equals(state)) {
                    showError(SourcesApi.message(body, context.getString(R.string.sources_common_error)));
                    return;
                }
                double p = body.optDouble("progress", 0);
                int pct = Double.isNaN(p) ? 0 : (int) Math.max(0, Math.min(100, Math.round(p)));
                progressBar.setProgress(pct);
                pctView.setText(context.getString(R.string.sources_percent, String.valueOf(pct)));
                statusView.setText(SourcesApi.message(body, context.getString(R.string.sources_phase_preparing)));
                handler.postDelayed(pollTask, POLL_MS);
            }

            @Override
            public void onFailure(String message) {
                // A dropped poll is not a failed format: keep asking.
                if (!done) handler.postDelayed(pollTask, POLL_MS);
            }
        });
        handler.postDelayed(pollTask, POLL_MS);
    }

    private void showError(String message) {
        showResult(context.getString(R.string.sources_error_title), message, true);
    }

    private void showResult(String title, String text, boolean error) {
        stopPolling();
        resultTitle.setText(title);
        resultTitle.setTextColor(context.getColor(error ? R.color.osmium_error : android.R.color.white));
        resultText.setText(text);
        showStep(stepResult);
    }

    private void stopPolling() {
        if (pollTask != null) handler.removeCallbacks(pollTask);
    }

    private void close() {
        done = true;
        stopPolling();
        dialog.dismiss();
        if (succeeded) listener.onFormatted();
    }

    /** Dismisses the dialog without callbacks, for when the owning activity goes away. */
    public void dismiss() {
        done = true;
        stopPolling();
        if (dialog.isShowing()) dialog.dismiss();
    }
}
