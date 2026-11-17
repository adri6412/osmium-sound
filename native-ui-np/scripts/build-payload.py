#!/usr/bin/env python3
"""Packs what the kiosk interface reads from disk into one file the page
unpacks into /app before Qt starts (site/qt/index.html), the same layout as
/opt/hifi-qt on the appliance (native-ui-qt/ci/build-payload.sh):

  qml/  icons/  assets/{vu,anim,remotes,*.png}  locales/  fonts/

Also writes skins.json, the VU meter looks for the pretend api_server
(list_vu_styles() in api_server.py: name and order from each skin.json).

Pack format (split into app.pack.N, see app.pack.json): 4-byte little-endian length of a JSON index
[{"p": path, "o": offset, "n": size}], the index, then the files.

usage: build-payload.py <osmium-sound checkout> <output dir>
"""
import json, os, struct, subprocess, sys

up, out = sys.argv[1], sys.argv[2]
ui = os.path.join(up, "native-ui-qt")
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"]
FONTS = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf", "DejaVuSerif.ttf"]

files = []   # (path in /app, bytes)


def add_tree(src, dest):
    for root, _, names in os.walk(src):
        for n in sorted(names):
            full = os.path.join(root, n)
            rel = os.path.relpath(full, src)
            files.append((os.path.join(dest, rel), open(full, "rb").read()))


# ── the kiosk's QML, without what only an Osmium Sound player can do ──────
# In the browser there is a Lyrion and nothing else: the settings about the
# appliance (network, updates, display, remotes, sources, CD, system...) are
# hidden (not removed: other parts of the interface open them by id), and so
# are the stores and the appliance's own parts of the Lyrion section. Every
# replacement must match exactly, or the build stops.
WEB_HIDDEN = ["sources", "cdRip", "audio", "btSpeakers", "remote", "network", "webRemote", "webRemoteIos", "ssh", "pointer",
              "uiResolution", "uiRefresh", "displayMode", "timezone", "systemInfo", "updates", "systemControls"]


# The "Now Playing only" web build (scripts/build-np.sh sets HIFI_NP_BUILD=1):
# the page that the appliance serves at /np shows just the Now Playing screen,
# driving the device itself. Everything else of the kiosk is left out, and the
# controls that would leave Now Playing are removed (see np_qml below).
NP_BUILD = os.environ.get("HIFI_NP_BUILD") == "1"


def qml_patch(name, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"build-payload: {name}: expected one match of {old[:70]!r}, found {text.count(old)}")
    return text.replace(old, new)


def np_qml(name, text):
    """Now Playing-only build. Pin the single Now Playing screen on and remove
    the controls that would navigate away from it or close it — the close
    (chevron) and settings buttons, the sleep timer, the clock (its tap starts
    the screensaver), and the taps that open the artist/album pages and the LED
    plate's BitPerfect/ReplayGain settings. KEPT: the VU and animation choosers,
    the VU/lyrics toggle, fullscreen (maximize/minimize), the queue, the player
    picker, the signal-path chip and LED path zone, and all the transport.
    Each patch must match exactly once, so any upstream drift stops the build."""
    if name == "App.qml":
        # Pin Now Playing on. MainScreen hides itself once `expanded` is
        # permanently true (its visible/shown are gated on !app.expanded), so
        # it never renders — no separate patch needed for it.
        text = qml_patch(name, text, "property bool expanded: false",
                         "property bool expanded: true")
        text = qml_patch(name, text,
                         "npSpring.set(Sys.startExpanded ? 0 : 1)\n        expanded = Sys.startExpanded",
                         "npSpring.set(0)\n        expanded = true")
        # Any request to collapse (close button, a settings jump) is a no-op.
        text = qml_patch(name, text,
                         "function setExpanded(on) {\n        if (expanded === on) return",
                         "function setExpanded(on) {\n        on = true\n        if (expanded === on) return")
        return text
    if name == "NowPlaying.qml":
        text = qml_patch(name, text,
            'RoundButton { x: root.pad; y: 12; width: 38; height: 38; icon: "chevron-down"; iconSize: 22; onClicked: root.collapse() }',
            'RoundButton { x: root.pad; y: 12; width: 38; height: 38; visible: false; icon: "chevron-down"; iconSize: 22; onClicked: root.collapse() }')
        text = qml_patch(name, text,
            "            id: clockPill\n            width: clockText.implicitWidth + 32; height: 36",
            "            id: clockPill\n            visible: false\n            width: clockText.implicitWidth + 32; height: 36")
        text = qml_patch(name, text,
            'x: root.width - root.pad - 34 * 2 - 8; y: 14; width: 34; height: 34; icon: "moon"; iconSize: 18',
            'x: root.width - root.pad - 34 * 2 - 8; y: 14; width: 34; height: 34; visible: false; icon: "moon"; iconSize: 18')
        text = qml_patch(name, text,
            'RoundButton { x: root.width - root.pad - 34; y: 14; width: 34; height: 34; icon: "settings"; iconSize: 18; onClicked: root.openSettings() }',
            'RoundButton { x: root.width - root.pad - 34; y: 14; width: 34; height: 34; visible: false; icon: "settings"; iconSize: 18; onClicked: root.openSettings() }')
        text = qml_patch(name, text,
            'enabled: Player.artistId !== ""; onClicked: Ui.app.openArtist(Player.artistId, Player.artist) }',
            'enabled: false; onClicked: Ui.app.openArtist(Player.artistId, Player.artist) }')
        text = qml_patch(name, text,
            'enabled: Player.albumId !== ""; onClicked: Ui.app.openAlbum(Player.albumId, Player.album) }',
            'enabled: false; onClicked: Ui.app.openAlbum(Player.albumId, Player.album) }')
        return text
    if name == "LedBar.qml":
        # Keep the Hi-Res/PCM/DSD column (opens the signal path); the
        # BitPerfect/ReplayGain tiles would open Settings, so they do nothing.
        text = qml_patch(name, text,
            'onClicked: modelData.which === "path" ? root.openPath() : root.openSetting(modelData.which)',
            'onClicked: { if (modelData.which === "path") root.openPath() }')
        return text
    if name in ("NpChooser.qml", "Dialogs.qml", "Wizard.qml"):
        # An overlay that grabs keyboard focus when it opens would, in the
        # browser, make Qt for WebAssembly focus its hidden input element — and
        # because the open happens inside a user tap, the device's native
        # on-screen keyboard pops up (seen when opening the VU/animation
        # chooser). /np is touch/mouse only, no remote, so dropping the
        # focus-grab costs nothing and keeps the keyboard down.
        if name == "NpChooser.qml":
            text = qml_patch(name, text,
                "        forceActiveFocus()",
                "        // np: no keyboard-focus grab (would raise the browser keyboard)")
        else:
            text = qml_patch(name, text,
                "    onActiveChanged: if (active) forceActiveFocus()",
                "    onActiveChanged: {}  // np: no keyboard-focus grab")
        return text
    if name == "TextField_.qml":
        # The /np page has nothing to type into (no search, no login): never
        # raise a keyboard. Two keyboards could appear: the app's own QML
        # VirtualKeyboard (asked for through vkOpen), AND — because /np runs in
        # a browser — the device's native on-screen keyboard, which Qt for
        # WebAssembly pops up whenever an editable TextInput takes focus. So we
        # neuter vkOpen AND make the field non-focusable and read-only, and drop
        # the tap that focuses it, so neither keyboard can ever come up.
        text = qml_patch(name, text,
            "property var vkOpen: function(field) { if (Ui.vk) Ui.vk.open(field) }",
            "property var vkOpen: function(field) {}")
        text = qml_patch(name, text,
            "        activeFocusOnPress: true",
            "        activeFocusOnPress: false\n        readOnly: true")
        text = qml_patch(name, text,
            "        onClicked: { input.forceActiveFocus(); root.openVk() }",
            "        onClicked: {}")
        return text
    return text


def cut(name, text, start, end):
    """Removes from `start` up to (not including) `end`, both found once."""
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        sys.exit(f"build-payload: {name}: cannot cut {start[:50]!r} .. {end[:50]!r}")
    return text[:text.index(start)] + text[text.index(end):]


def web_qml(name, text):
    if NP_BUILD:
        # The Now Playing-only build never shows MainScreen/Browser/Settings, so
        # it skips the demo's power-button and Settings-section cuts entirely
        # (those are tied to the public demo's upstream SHA) and applies only the
        # Now Playing patches.
        return np_qml(name, text)
    if name == "Browser.qml":
        # the power button of the tab bar: reboot and shut down the appliance
        return qml_patch(name, text, """        Item {
            id: powerBtn
            width: 40; height: 40""", """        Item {
            id: powerBtn
            visible: false
            width: 0; height: 40""")
    if name != "SettingsTab.qml":
        return text
    for sec in WEB_HIDDEN:
        line = next((l for l in text.splitlines() if l.strip().startswith('{ id: "%s",' % sec)), None)
        if not line or "hidden: true" in line:
            sys.exit(f"build-payload: SettingsTab.qml: section {sec} not found")
        text = text.replace(line, line.rstrip().rstrip(",").rstrip("}").rstrip() + ", hidden: true }" + ("," if line.rstrip().endswith(",") else ""))
    text = qml_patch(name, text, "        vuStoreRows(lang)\n    }", "    }")
    text = qml_patch(name, text, "        animStoreRows(lang)\n", "")
    # Lyrion section: the library and the grouping of players stay; the
    # device's name, its server role, installing Lyrion, its skin and the
    # archive of online information are the appliance's
    text = cut(name, text, '        help("settings.multiroom.help")\n        label("settings.multiroom.name.title")',
               "        // the library: what the server has indexed, and a refresh on demand")
    text = cut(name, text, "        // credits, biographies and album details from MusicBrainz and Wikipedia",
               "        if (remoteNote()) return\n        if (!havePlayer) { note(Tr.t(\"settings.playback.noPlayer\"), \"dark\"); return }\n        if (!cfg.players.length)")
    return text


for n in sorted(os.listdir(os.path.join(ui, "qml"))):
    if n.endswith(".qml"):
        text = open(os.path.join(ui, "qml", n), encoding="utf-8").read()
        files.append(("qml/" + n, web_qml(n, text).encode("utf-8")))
for n in sorted(os.listdir(os.path.join(ui, "icons"))):
    if n.endswith(".svg"):
        files.append(("icons/" + n, open(os.path.join(ui, "icons", n), "rb").read()))
for d in ("vu", "anim", "remotes"):
    add_tree(os.path.join(ui, "assets", d), "assets/" + d)
for n in sorted(os.listdir(os.path.join(ui, "assets", "ledbar"))):
    files.append(("assets/" + n, open(os.path.join(ui, "assets", "ledbar", n), "rb").read()))
for lang in ("en", "it"):
    files.append((f"locales/{lang}.json", open(os.path.join(up, "src", "i18n", "locales", lang + ".json"), "rb").read()))
# the third-party notices: the same array the appliance shows (build-payload.sh)
tpn = subprocess.run(["node", "-e", """
  const fs = require('fs');
  const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^export const thirdPartyNotices =/m, 'module.exports =');
  const m = { exports: {} }; new Function('module', 'exports', src)(m, m.exports);
  process.stdout.write(JSON.stringify(m.exports));
""", os.path.join(up, "src", "data", "thirdPartyNotices.js")], check=True, capture_output=True).stdout
files.append(("locales/third_party.json", tpn))
for f in FONTS:
    path = next((os.path.join(d, f) for d in FONT_DIRS if os.path.exists(os.path.join(d, f))), None)
    if not path:
        sys.exit(f"build-payload: font {f} not found (install fonts-dejavu-core)")
    files.append(("fonts/" + f, open(path, "rb").read()))

index, blobs, off = [], [], 0
for p, b in files:
    index.append({"p": p, "o": off, "n": len(b)})
    blobs.append(b)
    off += len(b)
head = json.dumps(index, separators=(",", ":")).encode()
os.makedirs(out, exist_ok=True)
pack = struct.pack("<I", len(head)) + head + b"".join(blobs)
# Cloudflare Pages serves files up to 25 MiB: the pack goes out in parts
# (app.pack.0, .1, ...) that the page joins again, listed in app.pack.json
PART = 20 * 1000 * 1000
parts = []
for i in range(0, len(pack), PART):
    name = "app.pack.%d" % len(parts)
    with open(os.path.join(out, name), "wb") as fh:
        fh.write(pack[i:i + PART])
    parts.append(name)
json.dump({"parts": parts, "size": len(pack)}, open(os.path.join(out, "app.pack.json"), "w"))

skins = []
vu = os.path.join(ui, "assets", "vu")
for sid in sorted(os.listdir(vu)):
    try:
        meta = json.load(open(os.path.join(vu, sid, "skin.json"), encoding="utf-8"))
    except (OSError, ValueError):
        continue
    name = meta.get("name") if isinstance(meta.get("name"), dict) else {"en": sid, "it": sid}
    skins.append({"id": sid, "name": {"en": name.get("en", sid), "it": name.get("it", name.get("en", sid))},
                  "order": meta.get("order", 50) if isinstance(meta.get("order", 50), int) else 50, "source": "builtin"})
skins.sort(key=lambda s: (s["order"], s["id"]))
json.dump([{k: s[k] for k in ("id", "name", "source")} for s in skins], open(os.path.join(out, "skins.json"), "w"))
print(f"build-payload: {len(files)} files, {off / 1e6:.1f} MB, {len(skins)} VU looks")
