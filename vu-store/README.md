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

The designer's layered PNGs (2850x1503 canvas, 2850x998 for Titanium) are not
in the repository. The needle is cut out of the "lancette" layer with
`vu-skin-build.py needle LANCETTE --x X0,X1 --top T --to B`, then built with
`--needle-pivot` = needle axis − X0, dial pivot Y − T (all source-artwork
pixels):

| id | from | needle cut | --needle-pivot | --meter (left, right) | --angles |
|---|---|---|---|---|---|
| `copper` | VU Dagostino: under backplate + quadranti, over frame esterno 2 (v2) | 715,790 / 340..875 | 34.5,557.93 | 744.31,897.93 · 2070.41,898.14 | -44.5,47.65 |
| `golden` | VU Golden: under quadranti, over frame | 700,775 / 280..1180 | 34.1,949.77 | 736.58,1229.77 · 2103.58,1231.77 | -34.1,34.3 |
| `aluminium` | VU Aluminium Style: under quadrante fix, over frame; v2 lancette | 750,830 / 230..1020 | 38.5,1041.91 | 796.59,1271.91 · 2024.46,1275.09 | -34.6,33.0 |
| `glossy` | VU Glossy: under quadrante, over frame | 650,936 / 347..1170 | 143.0,761.5 | 793.0,1108.5 · 2014.0,1108.5 | -44.15,43.4 |
| `titanium` | VU Titanium: under quadrante, over frame | 610,896 / 158..805 | 143.0,862 | 753.0,1020 · 2100.0,1020 | -38.86,39.17 |

The v2 Aluminium needle leans slightly in the artwork (tip at x 792, collar
at 788.5): its axis is the collar's centre.

The Aluminium scale is light on dark: `measure` looks for dark pixels, so its
pivots were measured on the bright ones instead. For Golden, `measure` reads
the dial's dark border as the outer ticks (±43°): the scale ends are ±34°.

Glossy and Titanium draw the needle, its collar and its coil in one "lancette"
layer, and the whole moving part turns together, like every other meter here:
plain `needle` with no `--cut`, cut wide enough to take the coil in (286
columns), and the frame is the only `--over`.

Their pivots are not the ones `measure` prints. Glossy turns on the coil's own
axis, not on the centre of its scale arc, which sits 216 px lower: from there
the coil turns on the spot, inside the frame's bracket, and the ticks in
between are off by at most 0.7 % of full scale. The Titanium scale is dead
straight, so there is no arc to fit at all, and the needle only reaches −20
and +3 turning around a point 671 px under the scale bar. Its coil does swing
out of the bracket, but it ends up behind the opaque part of the bezel; what
stays in sight is the shaft and its brass collar, which follow the needle.

Check the sprite over the whole sweep: `VuPanel.qml` does not clip the needle
to the panel, so a corner that leaves the canvas is drawn over the Now Playing
background.
