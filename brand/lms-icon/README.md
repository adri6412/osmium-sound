# Osmium player icon for Material Skin

`osmium.svg` is the player icon to hand to Material Skin's author (cpd73) so
that Osmium units get their own icon in the player list and on the Information
page, instead of the generic speaker every unrecognised SqueezeLite gets.

Derived from the Osmium Sound logo: the "OS" monogram, reduced to a single flat
colour because Material recolours these icons per theme (see below).

## What the player reports to Lyrion

`/etc/default/squeezelite` runs squeezelite with `-M Osmium`, so an Osmium
unit announces itself as:

| SlimProto field | Value          | Where it comes from                      |
|-----------------|----------------|------------------------------------------|
| `Model`         | `squeezelite`  | hardcoded in the binary, cannot change   |
| `ModelName`     | `Osmium`       | `-M`, see `apply.d/0059-squeezelite-model-name.sh` |

`Osmium` — the product name, not the full "Osmium Sound" and not the per-device
name an owner can set with `-n`. That exact string is the key Material matches on.

## The two things Material needs

1. **The icon**, dropped in as
   `MaterialSkin/HTML/material/html/images/osmium.svg`.

2. **The mapping**, an entry inside the existing `"squeezelite"` block of
   `MaterialSkin/HTML/material/html/misc/player-icons.json`, alongside
   `SqueezeLiteWin`, `WiiM Player` and the rest:

   ```json
   "squeezelite": {
       "Osmium": { "svg": "osmium" }
   }
   ```

   Material resolves the icon as `playerIcons[player.model][player.modelname]`,
   an exact string match, so the key must be exactly `Osmium`.

## Format rules these icons must follow

Verified against Material 6.4.6, `Plugin.pm::_svgHandler`, which serves every
icon through `/material/svg/<name>?c=<hex>` and rewrites its colours on the way
out:

```perl
$svg =~ s/#000/$colour/g;
$svg =~ s/fill\s*=\s*"[#0-9a-fA-F\.]+"/fill="${colour}"/g;
$svg =~ s/stroke\s*=\s*"[#0-9a-fA-F\.]+"/stroke="${colour}"/g;
```

So:

* **24×24, `viewBox="0 0 24 24"`** — same as every other icon in that folder.
* **One flat colour, written literally as `#000`.** The colour is replaced at
  request time with `#333` on the light theme and `#edece7` on the dark one, so
  the file must never depend on its own colours. Gradients and multi-colour
  artwork survive the substitution unchanged and would come out wrong on one of
  the two themes — that is why the logo's gold-and-silver treatment is dropped
  here.
* **`fill="none"` is safe** (it does not match the hex character class) and
  `stroke="#000"` is recoloured like any fill, so the outline strokes this icon
  is drawn with are handled correctly.

## Trying it without waiting for a release

`_svgHandler` looks in `<LMS prefs dir>/material-skin/images/<name>.svg` when the
plugin's own folder has no such file, so dropping `osmium.svg` there is enough to
test the artwork on a live server. Only the artwork, though: `player-icons.json`
is read from inside the plugin and has no equivalent override, so the automatic
model-name → icon mapping really does need the upstream change.

## Alternatives

`alternatives/` holds the other candidates that were drawn and compared at 16,
24, 32, 48 and 96 px on both themes. They exist so the mark can be swapped
without redrawing; delete the folder once the choice is settled.

| File                       | Mark                                             |
|----------------------------|--------------------------------------------------|
| `osmium-o-wave.svg`        | the "O" ring next to the logo's waveform          |
| `osmium-vinyl.svg`         | ring and centre hole — the website favicon's mark |
| `osmium-wave-in-ring.svg`  | waveform enclosed in the ring                     |
| `osmium-vinyl-play.svg`    | record with the logo's central play triangle      |
