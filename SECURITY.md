# Security Policy

## Supported Versions

Osmium Sound (formerly HiFi Media Player) ships as a full appliance image (OS + Electron app) updated in place via the OTA system. Because every device is expected to update to the latest release on its channel, only the most recent stable release receives security fixes.

| Version                 | Supported          |
| ------------------------ | ------------------ |
| 2.5.14 (latest stable)   | :white_check_mark: |
| < 2.5.14                 | :x: (please update via OTA or the latest ISO) |

Pre-release/dev builds (`-dev.N` suffix, `svil` branch) are not covered by this policy — they exist for internal testing only.

## Web administration & first-boot provisioning (security model)

The appliance can run **headless** (no screen) and is then managed from a web
admin UI served by `webui_server.py`. Its security model, and the deliberate
trade-offs:

- **Two independent auth systems, by design.** The web admin has its **own
  username/password account** (created at first setup, stored hashed in
  `/etc/hifi-player/webui.db`). The Android companion keeps its separate
  **pairing-token** system on port 8080. They never share credentials. The
  companion can only toggle display mode (non-destructive); it cannot factory
  reset (that needs the web admin password).
- **The system API stays loopback-only.** `api_server.py` remains bound to
  `127.0.0.1` and unauthenticated. `webui_server.py` is the only bridge and
  proxies a **whitelisted** set of calls to it, gated by the session. The
  whitelist is **partitioned**: during first-boot setup only a minimal pre-auth
  set is reachable (Wi-Fi, DAC, Lyrion install, mode choice, account creation) —
  never reboot/shutdown/SSH/OTA-apply/DSP/factory-reset.
- **TLS is self-signed and per-device.** The cert + the cookie-signing key are
  generated on the device at first start and never shipped in the image, so no
  two units share key material. Because there is no public CA for a local
  appliance, **browsers show a one-time "not trusted" warning — this is
  expected**; the connection is still encrypted.
- **CSRF via double-submit token.** Every mutation requires a CSRF token
  matched against a cookie that is host-only and `SameSite=Strict`, so it is
  never attached to a request whose Host was spoofed (e.g. DNS rebinding) —
  neither the CSRF token nor the session cookie can be forged that way. The
  appliance is therefore reachable under any hostname or IP (custom mDNS
  name, Tailscale, plain LAN IP, ...) without a Host allowlist blocking
  legitimate access. The only concession to Host is during first-boot/
  recovery setup: while the hotspot AP is up, an unrecognized Host is
  redirected to the captive portal instead of served directly.
- **Destructive actions re-validate the password.** Factory reset (and the web
  password change) require re-entering the admin password, so a stolen session
  cookie alone cannot wipe the box.
- **Setup hotspot.** During first boot an unconfigured unit raises an **open**
  (unencrypted) Wi-Fi hotspot (`Osmium-Setup-XXXX`). It was WPA2 with a fixed,
  documented passphrase until this was traced to an iOS incompatibility in the
  underlying wpa_supplicant software-AP handshake (invalid MIC on message 2/4,
  a known upstream issue) — the passphrase gave no real barrier against a
  targeted attacker anyway (it's public), so dropping it fixes iPhone setup at
  no material cost. Accepted residual risk: anyone in RF range can reach the
  minimal pre-auth set on an *unconfigured* unit, and can now also observe the
  home Wi-Fi password in the clear as it's submitted (setup itself is plain
  HTTP). This is a home appliance with a ~2 minute setup window, and the
  pre-auth set has no destructive endpoint.
- **Password recovery.** If the web admin password is lost: reset it from the
  on-screen kiosk (physical access), or factory reset (which also clears it).

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report it privately using one of these methods:

- Open a [GitHub Security Advisory](https://github.com/adri6412/osmium-sound/security/advisories/new) (preferred — keeps the report private until resolved).
- Email info@osmiumsound.it with details of the issue.

Please include as much of the following as you can:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, including affected component (Electron app, backend service, Android companion app, OS/OTA update mechanism, distro build, etc.).
- Version/build number or commit hash where the issue was found.

### What to expect

- **Acknowledgement:** within 5 business days.
- **Status updates:** at least every 2 weeks while the report is triaged and fixed.
- **If accepted:** a fix will be prepared and released as a patch version. Given the OTA distribution model, updates are pushed to the `main`/stable channel and devices receive them automatically (or on next manual check).
- **If declined:** you'll receive an explanation of why the report was not considered a valid security issue.

### Scope

This policy covers:

- The Electron application and its Node/main-process code.
- The backend/API services included in this repository.
- The Android companion app (`android-companion/`).
- The OTA update client/server and update-signing pipeline.
- The distro/appliance build (`live-build` based ISO).

Out of scope: issues in third-party dependencies (report them upstream), and vulnerabilities requiring physical access to an already-compromised device.
