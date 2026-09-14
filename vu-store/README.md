# VU meter store

The skins offered for download on the devices, from
`https://file.osmiumsound.it/vu/`. One folder per skin, as built by
`native-ui-qt/tools/vu-skin-build.py build ... --id <id> --version <n>`:
`skin.json` (with `id` and `version`) plus the images it names.

Publishing is the **Publish the VU meter store** workflow (manual run). It
packs every folder here into `<id>-<version>.vupak` with its preview, writes
`index.json`, signs it with the OTA signing key the devices already trust and
uploads everything to R2. Devices install only what the signed list names and
update the skins they already downloaded when the version goes up.

Rules:

- **Raise `version`** for any change to a published skin: packages are
  immutable (`<id>-<version>.vupak` is cached for good) and devices only
  update when the number grows.
- The `id` must not match a skin shipped in `native-ui-qt/assets/vu/`: a
  device offers only what it does not already have.
- A skin using effects (`format` 2) is shown as "needs an update" on devices
  whose interface does not know that format yet.
- No brand names in `name`: generic names only.
- Removing a folder removes the skin from the list; devices that downloaded it
  keep it until the owner removes it.
