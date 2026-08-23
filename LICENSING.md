# Licensing

Osmium Sound is **dual-licensed**. Copyright © 2026 Adriano Frongillo.

## 1. Open-source license (default): AGPL-3.0-only

All code authored by this project — the Electron/React kiosk, the Vue web admin,
the Python services, the distro/ISO packaging, Osmium Flasher, the "Osmium"
theme/CSS for Material Skin, and the hardware design files — is licensed under
the **GNU Affero General Public License, version 3 only (AGPL-3.0-only)**.
See [`LICENSE`](LICENSE) for the full text.

In short: you may use, study, modify and redistribute this software freely,
including commercially, **provided that** any distributed or network-hosted
derivative work is made available to its users under the same license, with
complete corresponding source code.

## 2. Commercial license

If the AGPL terms don't fit your use case — for example, you want to build a
commercial product or hosted service based on this code without publishing
your changes under the AGPL — a **separate commercial license** can be
purchased from the copyright holder.

Contact: **info@osmiumsound.it**

## Exceptions

| Path | License | Reason |
|------|---------|--------|
| `android-companion/` | **Apache-2.0** | Rebranded derivative of [android-squeezer](https://github.com/kaaholst/android-squeezer) (Apache-2.0, © Kurt Aaholst, Google Inc.); this project's modifications are contributed under the same license. Full text in `android-companion/docs/LICENSE.md`. |
| `flasher/vendor/file-type-compat/` | **MIT** | Vendored compatibility shim derived from the MIT-licensed `file-type` package. |
| Third-party components | Various | Bundled/redistributed under their own licenses — see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). |

## Earlier MIT releases

Before **2026-08-23** this project was published under the **MIT License**.
Every release, tag and commit published up to that date remains available
under MIT — that grant is irrevocable. The AGPL-3.0-only license applies to
this and all later versions of the code.

## Contributions

To keep dual licensing possible, external contributions require signing the
project's [Contributor License Agreement](CLA.md) — a one-time, one-click step
handled by a bot on your first pull request. Your contribution always also
remains available under the project's open-source license. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).
