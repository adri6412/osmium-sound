# shellcheck shell=sh
# 0044 — Beta-testing telemetry agent. RETIRED, deliberately left as a no-op.
#
# This migration used to ship and enable hifi-beta-agent.service, the daemon
# that registered every private-beta appliance with the cloud telemetry
# server and uploaded snapshots and HAR/perf captures to it. The private beta
# is over and the whole pipeline is gone: the agent, its unit, the capture
# scheduler in main/main.js and the bootstrap secret the release workflows
# used to bake in. The public site no longer discloses any data collection,
# so no device may keep doing it.
#
# Emptied rather than deleted: apply.d is cumulative — a device jumping from
# an old version straight to the newest runs only the latest payload, so the
# numbering has to stay dense and every past step has to stay accounted for.
# It cannot merely be *left* in place either: it enabled the unit
# unconditionally on every run, so it would fight 0052 below forever (and
# break the "a second apply.sh run reports changed=0" guarantee).
#
# 0052-remove-beta-agent.sh does the actual cleanup on devices that ran it.
