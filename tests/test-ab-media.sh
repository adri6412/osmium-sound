#!/bin/bash
# Osmium Sound — the music that lives on the legacy root, on the way to /data.
#
# A source can be an ordinary folder of the appliance's own root filesystem.
# On the A/B image that folder is not there any more (read-only squashfs, /mnt
# and /media on tmpfs), so hifi-ab-media.py moves it onto the data partition
# before the switch and makes Lyrion, Samba and Music Sources point at the new
# place. Everything that must NOT move is at least as important as what must:
# a disk that is only unplugged, the appliance's own playlist folder, /home
# (the image bind-mounts it, so the path already survives).
#
# Hermetic: a whole fake appliance in a temp dir, no Lyrion, no /data, no
# systemd.
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-ab-media.py"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

[ -f "$S" ] || { echo "missing $S"; exit 1; }
python3 -c 'import yaml' 2>/dev/null || { echo "SKIP: python3-yaml missing"; exit 0; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/run" "$T/etc/samba" "$T/data" "$T/srv/musica/rock" \
         "$T/home/hifi/Music" "$T/home/pippo" "$T/media/hifi-usb/leftover" \
         "$T/mnt/hifi-usb/unplugged" "$T/opt/altrove" \
         "$T/var/lib/squeezeboxserver/prefs" \
         "$T/var/lib/squeezeboxserver/playlists"
echo track > "$T/srv/musica/a.flac"
echo track > "$T/srv/musica/rock/b.flac"
echo track > "$T/home/hifi/Music/c.flac"
echo track > "$T/media/hifi-usb/leftover/d.flac"
echo track > "$T/mnt/hifi-usb/unplugged/e.flac"
echo track > "$T/opt/altrove/f.flac"
echo playlist > "$T/var/lib/squeezeboxserver/playlists/mix.m3u"

cat > "$T/etc/hifi-sources.json" <<'JSON'
{
  "sources": [
    {"id": "local-musica", "type": "local", "name": "/srv/musica", "path": "/srv/musica",
     "samba": true, "share": "Musica"},
    {"id": "local-Music", "type": "local", "name": "/home/hifi/Music", "path": "/home/hifi/Music"},
    {"id": "smb-nas-media", "type": "smb", "name": "nas/media",
     "mountpoint": "/mnt/hifi-sources/nas-media"}
  ]
}
JSON
cat > "$T/etc/samba/hifi-shares.conf" <<'CONF'

[Musica]
   path = /srv/musica
   read only = no
   force user = hifimusic
CONF
cat > "$T/var/lib/squeezeboxserver/prefs/server.prefs" <<'PREFS'
---
mediadirs:
  - /srv/musica
  - /home/hifi/Music
  - /mnt/hifi-usb/unplugged
  - /opt/altrove
playlistdir: /srv/musica/rock
PREFS
# Stand-in systemctl: records the calls, never does anything.
cat > "$T/bin/systemctl" <<'FAKE'
#!/bin/sh
echo "$@" >> "$HIFI_TEST_SYSCTL"
exit 0
FAKE
chmod +x "$T/bin/systemctl"

run() {  # <command...>
    HIFI_SYSROOT="$T" \
    HIFI_SYSTEMCTL="$T/bin/systemctl" \
    HIFI_LYRION_RPC="http://127.0.0.1:9/jsonrpc.js" \
    HIFI_TEST_SYSCTL="$T/systemctl-calls" \
        python3 "$S" "$@"
}
prefs() { python3 -c "
import sys, yaml
print(yaml.safe_load(open('$T/var/lib/squeezeboxserver/prefs/server.prefs'))[sys.argv[1]])" "$1"; }
srcpath() { python3 -c "
import json, sys
st = json.load(open('$T/etc/hifi-sources.json'))
print(next(s.get(sys.argv[2], '') for s in st['sources'] if s['id'] == sys.argv[1]))" "$1" "$2"; }

# ── 1. scan: what moves, what stays ─────────────────────────────────────
out=$(run scan 2>/dev/null)
action() { printf '%s' "$out" | python3 -c "
import json, sys
e = {x['path']: x['action'] for x in json.load(sys.stdin)['entries']}
print(e.get(sys.argv[1], 'none'))" "$1"; }
expect "a folder of /srv moves"                  "$(action /srv/musica)" move
expect "a folder of /home is copied, not moved"  "$(action /home/hifi/Music)" copy
expect "an unplugged disk is left alone"         "$(action /mnt/hifi-usb/unplugged)" none
expect "the appliance's playlist folder stays"   "$(action /var/lib/squeezeboxserver/playlists)" none
expect "a folder nobody manages is reported"     "$(action /opt/altrove)" unsupported
# the playlist folder is INSIDE /srv/musica: it travels with it, once
expect "a subfolder is not counted twice"        "$(action /srv/musica/rock)" none

# ── 2. move ─────────────────────────────────────────────────────────────
: > "$T/systemctl-calls"
run move >"$T/move.log" 2>&1
expect "move succeeds"                           "$?" 0
expect "the music is on the data partition"      "$(cat "$T/data/music/musica/a.flac" 2>/dev/null)" track
expect "subfolders came along"                   "$(cat "$T/data/music/musica/rock/b.flac" 2>/dev/null)" track
expect "the old folder is gone"                  "$([ -d "$T/srv/musica" ] && [ ! -L "$T/srv/musica" ] && echo dir || echo no)" no
expect "a symlink is left for the legacy slot"   "$(readlink "$T/srv/musica")" /data/music/musica
expect "/home is copied"                         "$(cat "$T/data/home/hifi/Music/c.flac" 2>/dev/null)" track
expect "...and left where it was"                "$(cat "$T/home/hifi/Music/c.flac" 2>/dev/null)" track
expect "an unplugged disk is untouched"          "$(cat "$T/mnt/hifi-usb/unplugged/e.flac" 2>/dev/null)" track
expect "a folder nobody manages is untouched"    "$(cat "$T/opt/altrove/f.flac" 2>/dev/null)" track

# ── 3. the pointers follow ──────────────────────────────────────────────
expect "Music Sources points at the new path"    "$(srcpath local-musica path)" /data/music/musica
expect "...and shows it"                         "$(srcpath local-musica name)" /data/music/musica
expect "a share keeps its name"                  "$(srcpath local-musica share)" Musica
expect "a /home source is not repointed"         "$(srcpath local-Music path)" /home/hifi/Music
expect "the share serves the new path"           "$(grep -c 'path = /data/music/musica' "$T/etc/samba/hifi-shares.conf")" 1
expect "smbd is asked to reload"                 "$(grep -c 'try-reload-or-restart smbd' "$T/systemctl-calls")" 1
expect "Lyrion's library follows"                "$(prefs mediadirs)" "['/data/music/musica', '/home/hifi/Music', '/mnt/hifi-usb/unplugged', '/opt/altrove']"
expect "the playlist folder follows too"         "$(prefs playlistdir)" /data/music/musica/rock
expect "Lyrion is stopped to rewrite its prefs"  "$(grep -c 'stop lyrionmusicserver' "$T/systemctl-calls")" 1
expect "...and started again"                    "$(grep -c 'start lyrionmusicserver' "$T/systemctl-calls")" 1

# ── 4. again: nothing left to do, and no second copy ────────────────────
run move >"$T/move2.log" 2>&1
expect "a second run is a no-op"                 "$?" 0
expect "no duplicate folder"                     "$([ -e "$T/data/music/musica-2" ] && echo yes || echo no)" no
expect "the music is still there"                "$(cat "$T/data/music/musica/a.flac" 2>/dev/null)" track
expect "the summary is written"                  "$([ -f "$T/run/hifi-ab-media.json" ] && echo yes || echo no)" yes

# ── 5. an interrupted run resumes into the same folder ──────────────────
mkdir -p "$T/srv/altra"; echo track > "$T/srv/altra/g.flac"
python3 - "$T" <<'PY'
import json, sys
p = sys.argv[1] + "/etc/hifi-sources.json"
st = json.load(open(p))
st["sources"].append({"id": "local-altra", "type": "local", "name": "/srv/altra", "path": "/srv/altra"})
json.dump(st, open(p, "w"))
PY
# a copy that was interrupted before the original was removed: the
# destination is written down BEFORE the copy, exactly as the script does it
mkdir -p "$T/data/music/altra"
python3 - "$T" <<'RESUME'
import json, sys
p = sys.argv[1] + "/data/music/.osmium-moved.json"
m = json.load(open(p))
m["/srv/altra"] = "/data/music/altra"
json.dump(m, open(p, "w"))
RESUME
run move >"$T/move3.log" 2>&1
expect "an interrupted move finishes"            "$?" 0
expect "...into the folder it had started"       "$([ -e "$T/data/music/altra-2" ] && echo yes || echo no)" no
expect "...with the files"                       "$(cat "$T/data/music/altra/g.flac" 2>/dev/null)" track
expect "...and the pointer updated"              "$(srcpath local-altra path)" /data/music/altra

# ── 6. moved, but the pointers were never rewritten ─────────────────────
# The window a power cut can land in: the folder is already on /data and gone
# from the root, so nothing sees it any more — only the list of moves does.
mkdir -p "$T/data/music/terza"; echo track > "$T/data/music/terza/h.flac"
ln -s /data/music/terza "$T/srv/terza"   # the safety net the move leaves behind
python3 - "$T" <<'ORPHAN'
import json, sys
T = sys.argv[1]
p = T + "/data/music/.osmium-moved.json"
m = json.load(open(p)); m["/srv/terza"] = "/data/music/terza"
json.dump(m, open(p, "w"))
p = T + "/etc/hifi-sources.json"
st = json.load(open(p))
st["sources"].append({"id": "local-terza", "type": "local",
                      "name": "/srv/terza", "path": "/srv/terza"})
json.dump(st, open(p, "w"))
ORPHAN
run move >"$T/move4.log" 2>&1
expect "a pointer left behind is repaired"       "$(srcpath local-terza path)" /data/music/terza

# ── 7. the new path has to be one Music Sources still accepts ───────────
# current_paths() re-validates every stored source against ALLOWED_LOCAL_ROOTS
# before handing it to Lyrion, so a /data/music path that is not in there
# would be dropped on the next Apply and the library would go with it.
if PYTHONPATH=. python3 -c 'import flask' 2>/dev/null; then
    expect "/data/music is an allowed source root" \
        "$(PYTHONPATH=. python3 -c "
import sources_server as ss
print(ss.DATA_MUSIC_ROOT in ss.ALLOWED_LOCAL_ROOTS and ss.DATA_MUSIC_ROOT in ss._BROWSE_ROOTS)")" True
fi

# ── 8. on an image slot there is nothing to relocate ────────────────────
# /home there IS /data/home (the initramfs binds it), so the only thing left
# to "copy" would be the folder onto itself.
mkdir -p "$T/usr/lib/osmium"; echo v1 > "$T/usr/lib/osmium/IMAGE_VERSION"
out=$(run scan 2>/dev/null)
expect "an image slot has nothing to move" \
    "$(printf '%s' "$out" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['entries']))")" 0
rm -rf "$T/usr/lib/osmium"

echo "test-ab-media: $pass ok, $fail failed"
[ "$fail" = 0 ]
