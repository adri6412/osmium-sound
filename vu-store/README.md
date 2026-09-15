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

## Sources

The designer's layered PNGs (2850x1503 canvas) are not in the repository.
The needle is cut out of the "lancette" layer with `vu-skin-build.py needle
LANCETTE --x X0,X1 --top T --to B`, then built with `--needle-pivot` =
needle axis − X0, dial pivot Y − T (all source-artwork pixels):

| id | from | needle cut | --needle-pivot | --meter (left, right) | --angles |
|---|---|---|---|---|---|
| `copper` | VU Dagostino.zip: under backplate + quadranti, over frame | 715,790 / 340..875 | 34.5,557.93 | 744.31,897.93 · 2070.41,898.14 | -44.5,47.65 |
| `golden` | VU Golden: under quadranti, over frame | 700,775 / 280..1180 | 34.1,949.77 | 736.58,1229.77 · 2103.58,1231.77 | -34.1,34.3 |
| `aluminium` | VU Aluminium Style: under quadrante fix, over frame | 760,835 / 265..1070 | 34.9,1006.91 | 796.59,1271.91 · 2024.46,1275.09 | -34.6,33.0 |

The Aluminium scale is light on dark: `measure` looks for dark pixels, so its
pivots were measured on the bright ones instead. For Golden, `measure` reads
the dial's dark border as the outer ticks (±43°): the scale ends are ±34°.
