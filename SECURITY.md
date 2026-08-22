# Security Policy

## Supported Versions

Osmium Sound (formerly HiFi Media Player) ships as a full appliance image (OS + Electron app) updated in place via the OTA system. Because every device is expected to update to the latest release on its channel, only the most recent stable release receives security fixes.

| Version                  | Supported          |
| ------------------------ | ------------------ |
| 2.5.21 (latest stable)   | :white_check_mark: |
| < 2.5.21                 | :x: (please update via OTA or the latest ISO) |

Pre-release builds are not covered by this policy — they exist for testing only:
`vX.Y.Z-dev.N` (the public **dev** channel, cut from the `svil` branch) and
`vX.Y.Z-dev.N-alphaM` (the private **alpha** channel, cut from the `alpha`
branch and only visible to devices explicitly unlocked for it). See
[`.github/workflows/TAG_CONVENTIONS.md`](.github/workflows/TAG_CONVENTIONS.md).

## Security model of the appliance

The appliance can run **headless** (no screen) and is then managed from a web
admin UI served by `webui_server.py`; the Android companion talks to
`sources_server.py`. The model, and the deliberate trade-offs:

- **The system API stays loopback-only.** `api_server.py` (root) is bound to
  `127.0.0.1:8000` and unauthenticated; nothing on the LAN can reach it
  directly. Everything LAN-facing goes through one of two gateways below, each
  of which forwards only an explicit **whitelist** of its routes.
- **Web admin: own account, cookie session, CSRF.** `webui_server.py` (port
  **80, plain HTTP**) has its **own username/password account** (created at
  first setup, password stored hashed in `/etc/hifi-player/webui.db`). The
  proxy whitelist is **partitioned**: during first-boot setup only a minimal
  pre-auth set is reachable (network, audio device, Lyrion, mode choice,
  account creation — `_PROVISION_ROUTES`), never reboot/shutdown/SSH/OTA
  apply/factory reset; after login the session unlocks the full
  `_AUTH_ROUTES` set. Every mutation requires a **double-submit CSRF token**
  matched against a cookie that is host-only and `SameSite=Strict`, so neither
  the CSRF token nor the session cookie can be forged by spoofing the `Host`
  header (DNS rebinding). The appliance is therefore reachable under any
  hostname or IP (custom mDNS name, Tailscale, plain LAN IP, …) without a Host
  allowlist blocking legitimate access; the only Host-based behaviour is that,
  while a setup/recovery hotspot is up, an unrecognized Host is redirected to
  the captive portal.
- **No TLS, by design.** The web admin used to serve a per-device self-signed
  certificate on :443. Every browser then showed a "connection not private"
  interstitial on first visit, which was worse UX than plain HTTP for a
  LAN/Tailscale-only admin panel, so it was dropped (`apply.d/0040-webui-drop-https.sh`).
  Consequence: the admin password travels in the clear **on your own LAN**;
  anyone who can sniff your LAN traffic can read it. Reach the box over
  Tailscale if you need an encrypted path from outside.
- **Companion: pairing token, limited surface.** The Android app
  authenticates to `sources_server.py` (port 8080, LAN-bound) with a **bearer
  pairing token** minted only from localhost (the kiosk screen or the web admin
  acting on the owner's behalf), shown as a QR code; failed attempts are
  rate-limited per IP. The two credential systems never mix. A pairing token
  reaches the sources/backup/Lyrion-skin routes and a fixed proxy list of the
  system API (`_SYSTEM_PROXY_ROUTES`: display mode, audio device, UI
  resolution/refresh, VU meter, multiroom, updates, OTA channel, SSH on/off,
  reboot/shutdown, names). It can **not** factory reset, create or change the
  shell/SSH login, change the web-admin account, or reconfigure the network —
  those need the web admin password or the touchscreen.
- **Destructive actions re-validate the password.** Factory reset (and the web
  password change) require re-entering the admin password, so a stolen session
  cookie alone cannot wipe the box.
- **Setup hotspot is open, and only raised when there is no other way in.**
  The live-USB **installer** raises an **open** (unencrypted) Wi-Fi hotspot
  (`Osmium-Setup-XXXX`) with a captive portal, because at that point there is
  no OS on disk and possibly no keyboard/touch at all. It was WPA2 with a
  fixed, documented passphrase until that was traced to an iOS incompatibility
  in wpa_supplicant's software-AP handshake — a public passphrase gave no real
  barrier anyway. The first-boot **setup** of an installed system raises **no
  hotspot**: the network step happens on the touchscreen and the phone reaches
  the box at its LAN address. An already-configured unit that loses all
  connectivity raises the same open hotspot again with a network-only
  recovery page. Accepted residual risk: anyone in RF range of an
  unconfigured/offline unit can reach that minimal pre-auth set and can observe
  the home Wi-Fi password as it is submitted (plain HTTP). This is a home
  appliance with a short setup window and no destructive pre-auth endpoint.
- **SSH off by default, no default login.** `openssh-server` ships disabled.
  The kiosk user `hifi` has no password and is not in `sudo`; `root` login over
  SSH is refused (`PermitRootLogin no`, enforced at build, at first SSH start,
  and by OS update). The Linux login is created from the web-admin account (or
  from the SSH panel) and is a real sudo user; enabling SSH is an explicit
  owner action. Remote access beyond the LAN is the owner's own Tailscale
  tailnet, never a vendor-operated one.
- **Updates.** The OS OTA payload (an arbitrary root script) is accepted only
  with a valid **Ed25519 signature** against the public key baked into the
  image (`/etc/hifi-player/ota-pubkey.pem`); downloads are HTTPS-pinned,
  size-bounded, extracted into a private temp dir and the script runs in a
  scrubbed environment. UI/System bundles are sha256-verified and swapped
  atomically. The ISO is signed with the same key and **Osmium Flasher refuses
  an unsigned image**. The owner can enrol their own signing key on the device
  (`hifi-ota-enroll-key.sh`, root-only, not network-reachable). Details in
  [ARCHITECTURE.md → OTA update system](ARCHITECTURE.md#ota-update-system).
- **Bootloader is never rewritten by an OTA** — on a headless fleet that can
  brick a unit with no way back in; Secure Boot / GRUB changes are build-time
  only (`apply.d/0010-secure-boot.sh`, intentionally a no-op).
- **Password recovery.** If the web admin password is lost: reset it from the
  on-screen kiosk (Settings → System controls → "Reset web interface
  password", physical access), or factory reset (which also clears it).
- **What the device does not do.** It records nothing about itself for the
  vendor: there is no telemetry agent, no HAR/performance capture, no
  remote-support key. Lyrion's own optional usage reporting (its *Analytics*
  plugin) is an unticked opt-in in the setup wizard.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report it privately using one of these methods:

- Open a [GitHub Security Advisory](https://github.com/adri6412/osmium-sound/security/advisories/new) (preferred — keeps the report private until resolved).
- Email support@osmiumsound.it with details of the issue.

Please include as much of the following as you can:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, including affected component (Electron app, web admin, backend service, Android companion app, OS/OTA update mechanism, distro build, flasher, etc.).
- Version/build number or commit hash where the issue was found.

### What to expect

- **Acknowledgement:** within 5 business days.
- **Status updates:** at least every 2 weeks while the report is triaged and fixed.
- **If accepted:** a fix will be prepared and released as a patch version. Given the OTA distribution model, updates are pushed to the `main`/stable channel and devices receive them automatically (or on next manual check).
- **If declined:** you'll receive an explanation of why the report was not considered a valid security issue.

### Scope

This policy covers:

- The Electron application and its Node/main-process code.
- The web admin (`admin-webui/`, `webui_server.py`) and the backend/API services included in this repository.
- The Android companion app (`android-companion/`).
- The OTA update client/server and update-signing pipeline.
- The distro/appliance build (`live-build` based ISO) and Osmium Flasher (`flasher/`).

Out of scope: issues in third-party dependencies (report them upstream), and vulnerabilities requiring physical access to an already-compromised device.
