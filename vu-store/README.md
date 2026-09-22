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

The designer's layered PNGs (2850x1503 canvas, 2850x1157 for Titanium) are not
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
| `titanium` | VU Titanium 2: under scala e magneti, over frame; red rod 57 px longer | 614,893 / 92..925 | 137.5,762.5 | 751.5,850.5 · 2096.5,850.5 | -45.31,44.86 |

The v2 Aluminium needle leans slightly in the artwork (tip at x 792, collar
at 788.5): its axis is the collar's centre.

The Aluminium scale is light on dark: `measure` looks for dark pixels, so its
pivots were measured on the bright ones instead. For Golden, `measure` reads
the dial's dark border as the outer ticks (±43°): the scale ends are ±34°.

Glossy and Titanium draw the needle, its collar and its coil in one "lancette"
layer, and the whole moving part turns together, like every other meter here:
plain `needle` with no `--cut`, cut wide enough to take the coil in (286
columns for Glossy, 279 for Titanium), and the frame is the only `--over`.

Both turn on the coil's own axis, so the coil turns on the spot in its housing
and the needle always comes out of it. That is not what `measure` prints:
Glossy's scale arc has its centre 216 px lower, and turning the needle there
walks it off the hub. Aimed from the coil instead, the ticks in between are
off by at most 0.7 % of full scale.

Titanium's scale is drawn straight, with two rules and ticks that lean but do
not radiate from one centre: fitting them gives no usable pivot (the lines miss
each other by 135 px, and −10 leans further than −20). Its geometry comes from
the artwork instead. The pivot is the coil, whose axis is also the centre of
the magnet disc in the "scala e magneti" layer, a clean 228 px circle at
749.5,850.5 and 2093.5,850.5. The angles point the needle at where the −20 and
the +3 tick cross the middle of the scale bar (y 316).

From there the needle as drawn is 57 px too short to reach those two marks. It
is lengthened by that much: only the red rod is resampled, the stem, collar and
coil keep their pixels and their rows. The needle is then long enough to run
behind the top bezel between levels 25 and 75, which is the price of a hinge
that stays where the artwork draws it. Putting the pivot further down — around
y 1130 — makes the needle as drawn fit exactly and clips nothing, but then the
brass collar slides out from under the hub cover at both ends, which is the
fault this artwork was redrawn to cure.

Check the sprite over the whole sweep: `VuPanel.qml` does not clip the needle
to the panel, so a corner that leaves the canvas is drawn over the Now Playing
background.
