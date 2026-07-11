# Security Policy

## Supported Versions

Osmium Sound (formerly HiFi Media Player) ships as a full appliance image (OS + Electron app) updated in place via the OTA system. Because every device is expected to update to the latest release on its channel, only the most recent stable release receives security fixes.

| Version                 | Supported          |
| ------------------------ | ------------------ |
| 2.5.14 (latest stable)   | :white_check_mark: |
| < 2.5.14                 | :x: (please update via OTA or the latest ISO) |

Pre-release/dev builds (`-dev.N` suffix, `svil` branch) are not covered by this policy — they exist for internal testing only.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report it privately using one of these methods:

- Open a [GitHub Security Advisory](https://github.com/adri6412/osmium-sound/security/advisories/new) (preferred — keeps the report private until resolved).
- Email info@adrianofrongillo.ovh with details of the issue.

Please include as much of the following as you can:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, including affected component (Electron app, backend service, Android companion app, OS/OTA update mechanism, distro build, etc.).
- Version/build number or commit hash where the issue was found.

### What to expect

- **Acknowledgement:** within 5 business days.
- **Status updates:** at least every 2 weeks while the report is triaged and fixed.
- **If accepted:** a fix will be prepared and released as a patch version. Given the OTA distribution model, updates are pushed to the `main`/stable channel and devices receive them automatically (or on next manual check). Credit will be offered in the release notes unless you prefer to stay anonymous.
- **If declined:** you'll receive an explanation of why the report was not considered a valid security issue.

### Scope

This policy covers:

- The Electron application and its Node/main-process code.
- The backend/API services included in this repository.
- The Android companion app (`android-companion/`).
- The OTA update client/server and update-signing pipeline.
- The distro/appliance build (`live-build` based ISO).

Out of scope: issues in third-party dependencies (report them upstream), and vulnerabilities requiring physical access to an already-compromised device.
