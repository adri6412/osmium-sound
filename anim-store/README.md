# Now Playing animation store

The animations offered for download on the devices, from
`https://file.osmiumsound.it/anim/`. One folder per animation, named after
its id. The four animations the interface ships (top-loading CD, CD player,
vinyl, cassette) are not here: they stay built in.

Publishing is the **Publish the animation store** workflow (manual run). It
packs every folder into `<id>-<version>.animpak` with its preview
(`native-ui-qt/tools/anim-store.py pack`), writes `index.json`, signs it with
the OTA signing key the devices already trust and uploads everything to R2.
Devices install only what the signed list names and update the animations
they already downloaded when the version goes up.

## A folder

- `anim.json`: `id` (the folder's name), `version` (an integer), `format`
  (the scene contract, below), `name` `{en, it}`, `scene` (the QML file the
  kiosk loads), optionally `order`, `author`, `license`.
- the scene's `.qml` files, its `.png` / `.jpg` images and any `.json` data,
  all flat (no subfolders), names `[A-Za-z0-9][A-Za-z0-9._-]*`.
- `preview.jpg`: a still of the scene for the store's card (under 1 MB). A
  scene cannot be drawn outside the kiosk, so it is taken on a device or in
  the development rig.

## The scene contract (format 1)

A scene is loaded like the built-in ones (`native-ui-qt/qml/NpAnimation.qml`)
and gets the same inputs; it declares the ones it uses. The same scene draws
the Now Playing panel, the full-screen view (just larger: it scales its design
to the box it is given) and the still of the Settings card.

- always: `assetsBase` (its own folder, with a trailing slash), `devScale`,
  `live` (false for the still of the Settings card: draw the final pose once,
  never run a timer), `active` (on screen), `playing`, `hasTrack`, `progress`
  (0..1), `artwork` (URL), `mediaKey` (changes with the album), `title`,
  `subtitle`;
- controls: `power`, `volume`, `volumeFixed`, and a `signal action(name,
  value)` with `play`, `pause`, `stop`, `prev`, `next`, `eject`, `volume`
  (`{level, final}`), `power`, `repeat`, `random`, `wind` (+1/-1), `windStop`,
  `track` (a queue position, 1-based);
- a display: `trackIndex`, `trackTotal`, `elapsed`, `duration` (seconds, 0
  unknown), `trackId`, `repeatMode`, `shuffleMode`, `trackTitle`, `trackArtist`;
- levels (this device's own audio): `levelL`, `levelR` (0..100).

It may import `QtQuick`, `QtQuick.Effects` and `QtQuick.Shapes`. Its own
components are other `.qml` files of the folder.

🚨 The kiosk runs on weak Intel graphics all day: nothing may animate at
frame rate unless the scene is visibly moving (a disc turning while playing),
and then from one timer that stops when it stops; paused, stopped, hidden or
still, the scene must be fully idle. See the built-in scenes.

## Rules

- **Raise `version`** for any change: packages are immutable
  (`<id>-<version>.animpak` is cached for good) and devices only update when
  the number grows.
- A scene needing a newer contract raises `format`: devices whose interface
  does not know it list it as "needs an update" and never install it.
- A scene is code that runs on every device that downloads it: review it like
  a change to the interface, then publish.
- No brand names in `name`: generic names only.
- Removing a folder removes the animation from the list; devices that
  downloaded it keep it until the owner removes it.
