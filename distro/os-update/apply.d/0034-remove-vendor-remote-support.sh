# shellcheck shell=sh
# 0034 — Retire the vendor "remote support" mechanism (GitHub-Actions-minted
# Tailscale keys, .github/workflows/remote-support-mint.yml, the low-value
# device PAT). Tailscale itself STAYS — it is repurposed so the OWNER can
# join the appliance to their OWN tailnet (see api_server.py set_tailscale)
# — only the vendor-support plumbing goes away.
#
# Deliberately does NOT touch the 'support' system user 0029 created: 0029 is
# a frozen, cumulative migration (the OS channel's contract forbids rewriting
# or deleting a shipped migration) that unconditionally recreates that user
# on every OS update if missing. Deleting it here would just have 0029
# recreate it on the very next update, forever — an infinite churn that would
# also break the idempotency guarantee (two apply.sh runs back to back must
# both report changed=0). It's harmless to leave: locked, no password, and
# nothing advertises Tailscale SSH to it any more (set_tailscale never passes
# --ssh), so it can no longer be reached.
#
# One-time cleanup, gated on the leftover PAT file from 0030 — NOT on
# Tailscale's current connection state: once that file is gone (first
# successful run, or a device that never used remote support), this is a
# permanent no-op and never touches Tailscale again, so it can't ever
# disconnect an owner's own tailnet joined via the new Settings toggle on a
# later OS update. 0030 itself never recreates the file (it only writes one
# shipped in the payload, and the release pipeline stops shipping one), so
# there is no equivalent churn risk here.
#
# Only logs the device out of Tailscale if it is currently registered under
# the old vendor hostname prefix ("hifi-support-...", see the retired
# TAILSCALE_HOSTNAME_PREFIX) — so if an owner already used the new toggle to
# join their own tailnet in the brief window between the System and OS steps
# of a combined update, this leaves that connection alone.
#
# Never reboots — everything here takes effect immediately.

PAT_FILE=/etc/hifi-player/github-support-pat

if [ ! -f "$PAT_FILE" ]; then
    exit 0
fi

if command -v tailscale >/dev/null 2>&1; then
    ts_status=$(tailscale status --json 2>/dev/null || true)
    case "$ts_status" in
        *'"HostName":"hifi-support-'*)
            if tailscale logout >/dev/null 2>&1; then
                mark_changed "logged out of the vendor remote-support tailnet"
            else
                log_warn "could not log out of the old remote-support tailnet (will retry next update)"
            fi
            ;;
    esac
fi

rm -f "$PAT_FILE"
mark_changed "removed leftover remote-support GitHub PAT"
