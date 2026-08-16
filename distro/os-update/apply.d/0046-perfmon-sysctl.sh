# shellcheck shell=sh
# 0046 — restore CAP_PERFMON's perf_event bypass (Debian raises the default).
#
# hifi-beta-agent.service and hifi-api.service both run intel_gpu_top under
# AmbientCapabilities=CAP_PERFMON specifically so they don't need full root
# to read GPU busy% -- but Debian's kernel ships perf_event_paranoid=3 by
# default, a Debian-only level that drops the standard CAP_PERFMON bypass and
# requires CAP_SYS_ADMIN instead. The services have been silently getting
# "Failed to initialize PMU! (Permission denied)" from intel_gpu_top since
# whenever they were first written -- gpu_busy_pct() swallows the failure and
# just returns None, so nothing ever surfaced it. Level 2 is upstream's own
# "no unprivileged perf at all" default and is the highest level that still
# honors CAP_PERFMON, restoring the behaviour these services already assumed
# without widening their capability grant.
#
# ensure_file_content is idempotent; sysctl -p only touches the live value
# when the file actually changed, so already-applied devices don't reload on
# every update.

ensure_file_content /etc/sysctl.d/30-perf-event-paranoid.conf 644 root:root <<'EOF'
kernel.perf_event_paranoid = 2
EOF

if migration_changed; then
    sysctl -p /etc/sysctl.d/30-perf-event-paranoid.conf >/dev/null 2>&1 || true
fi
