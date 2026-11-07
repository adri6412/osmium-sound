# Osmium Convert — LMS plugin

The single mechanism behind the appliance's per-player conversion control
(Off / PCM upsampling / DSD). The appliance no longer writes
`custom-convert.conf` itself: it sends this plugin a CLI command over the
standard LMS port 9000, to whichever Lyrion the player follows.

## Files
- `Plugin.pm` — `osmiumconvert set|clear|status` CLI; writes its own
  `custom-convert.conf`; reloads the conversion tables with no server restart;
  persists rules in its prefs and re-applies them at init.
- `Bin/osmium-convert` — portable SoX helper (arg-driven; no appliance paths).
  DSD needs `sox_ng` with the `sdm` effect; PCM upsampling needs any `sox`.
- `install.xml`, `strings.txt` — plugin manifest and strings.
- `repo.xml` — self-hosted repository descriptor for third-party servers.

## How it is installed on the appliance
This directory is the **read-only source**, shipped in the image at
`/usr/local/share/osmium/lms-plugins/OsmiumConvert`. On every boot
`hifi-lyrion-plugins-ensure.sh` copies it into the local server's writable,
scanned plugin directory (`<cachedir>/InstalledPlugins/Plugins/OsmiumConvert`,
cachedir = `/var/lib/squeezeboxserver/cache`) when missing or when the
`install.xml` version differs. Not a first-boot job: the RAUC root is read-only
and replaced whole on OTA, so the plugin is re-asserted each boot.

## CLI contract (what the appliance calls over jsonrpc.js)
    osmiumconvert set   <mac> dsd <dsd64|dsd128|dsd256> <clans-8|sdm-8>
    osmiumconvert set   <mac> pcm <x2|x4|max>           <cap-hz>
    osmiumconvert set   <mac> off
    osmiumconvert clear <mac>
    osmiumconvert status
`set`/`clear` are accepted only for a MAC that is a player currently connected
to this server. `status` returns `has_sox`, `has_sox_ng`, `has_sdm`, `dsd`
(available here?), `upsample`, and the current `rules_loop`. A `set dsd` on a
server without `sox_ng`+`sdm` returns `error: noServerTools`.

## Validate on hardware (Dell .133) — BEFORE wiring the appliance to it
These are the plan's Phase-1 unknowns to confirm on a real Lyrion 9.1.x:
1. **Install dir**: confirm the server scans
   `/var/lib/squeezeboxserver/cache/InstalledPlugins/Plugins/OsmiumConvert` and
   that it is writable by the `squeezeboxserver` user. If the scanned dir
   differs, adjust `HIFI_LMS_CACHE`/the ensure script.
2. **Load**: after copying the plugin there and restarting Lyrion, it appears in
   Settings → Plugins and `initPlugin` runs (check the server log,
   `plugin.osmiumconvert`).
3. **CLI**: `osmiumconvert status` answers over
   `http://127.0.0.1:9000/jsonrpc.js` and reports `has_sox_ng`/`has_sdm`
   correctly for this box (appliance has sox_ng at `/usr/local/bin`).
4. **Reload without restart**: `osmiumconvert set <mac> dsd dsd64 clans-8` on a
   connected player makes the next track play as DSD **without** restarting the
   server (confirms the clear-globals + `loadConversionTables()` reload).
   Change to `pcm x2 0`, then `clear`, and confirm each takes effect live.
5. **Persistence**: after a server restart the last-set rule is re-applied
   (prefs survive), and the rule is still in the plugin's `custom-convert.conf`.

Only after this passes do we wire `api_server.py` to drive the plugin (Phase 2)
and remove the player-side path.
