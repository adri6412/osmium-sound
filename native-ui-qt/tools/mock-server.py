#!/usr/bin/env python3
"""Finto apparecchio per lo sviluppo senza il Dell: Lyrion (:9000, JSON-RPC +
copertine), api_server (:8000), sources_server (:8080) e il daemon dei VU
(:9001, WebSocket). Dati fissi, sufficienti a disegnare tutte le schermate.
"""
import asyncio, base64, hashlib, json, math, os, random, struct, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
COVER = os.environ.get("MOCK_COVER", os.path.join(HERE, "..", "..", "logo osmium.jpg"))
STATE = {
    "mode": "play", "time": 116.0, "duration": 330.0, "volume": 40, "index": 2, "shuffle": 0, "repeat": 0, "sleep": 0, "power": 1,
    "prefs": {"replayGainMode": "0", "transitionType": "0", "transitionDuration": "0", "digitalVolumeControl": "1"},
    "vu": os.environ.get("MOCK_VU", "1") != "0", "vu_style": os.environ.get("MOCK_VU_STYLE", "classic"),
    "np_animation": os.environ.get("MOCK_NP_ANIMATION", "none"), "autoexpand": 0, "ota": {"state": "idle"}, "lang": "it",
    "display_mode": "gui", "ui_resolution": "auto", "ui_refresh": "native", "pointer": True, "ssh": False, "player_enabled": True,
    "lms_mode": "local", "lms_host": "", "tz": "Europe/Rome", "device_name": "Osmium", "ota_channel": "dev", "lyrion_channel": "release",
    "audio": "hw:CARD=DAC,DEV=0", "shell_user": "", "pldir": "/srv/music/playlist", "skin": "osmium", "fmt": {"state": "idle"},
    "install": {"state": "idle"}, "cd": {"no_disc": True}, "cdrip": {"state": "idle"},
    # the top-bar connectivity icon: internet | lan | offline, wired | wireless | none
    "net": os.environ.get("MOCK_NET", "internet"), "net_type": os.environ.get("MOCK_NET_TYPE", "wired"),
    # Ricerca dei dispositivi in rete: uno con nome mDNS, uno che chiede la
    # password (192.168.0.60) e uno trovato solo dalla sonda sulla porta.
    "smbscan": {"t0": 0.0, "hosts": [
        {"ip": "192.168.0.50", "name": "SYNOLOGY", "sources": ["mdns", "port"]},
        {"ip": "192.168.0.60", "name": "PC-SALOTTO", "sources": ["netbios"]},
        {"ip": "192.168.0.77", "name": "", "sources": ["port"]},
    ]},
}
ARTISTS = ["Toto", "Pink Floyd", "Dire Straits", "Ludovico Einaudi", "Ólafur Arnalds", "¡Uno!", "03 Greedo", "Daft Punk", "Miles Davis", "Nils Frahm", "Radiohead", "Beethoven"]
ALBUMS = [(i + 1, f"Album {i + 1} — {a}", a, (i % 12) + 1) for i, a in enumerate(ARTISTS * 2)]
QUEUE = [("Rosanna", "TOTO", "TOTO IV"), ("Africa", "TOTO", "TOTO IV"), ("Hold the Line", "TOTO", "Toto"), ("Time", "Pink Floyd", "The Dark Side of the Moon"), ("Money", "Pink Floyd", "The Dark Side of the Moon")]
T0 = time.time()
# Scenarios (env):
#   MOCK_LONG_QUEUE=1        40 tracks in the queue (scrolling tests, #100)
#   MOCK_NET=lan|offline     the top-bar connectivity icon (default internet);
#   MOCK_NET_TYPE=wireless   wired by default, `none` = no link at all
#   MOCK_WIFI_FAIL=1         Settings → Network → "Connect to Wi-Fi" fails
#   MOCK_WIRED_FAIL=1        ... and so does "Use wired"
#   MOCK_SHARED_LMS=N        somebody else's Lyrion (#99): the list holds a
#                            phone player from the start, our "Osmium" only
#                            shows up N seconds after the mock started (LAN
#                            address, not loopback); the status of the phone
#                            carries its own player_name
#   MOCK_VU_STORE=1          the VU meter store runs on the real api_server.py
#                            code (and so does /vu_style): configure it with
#                            HIFI_VU_STORE_URL / HIFI_VU_STORE_PUBKEY /
#                            HIFI_VU_STORE_DIR / HIFI_VU_STORE_STATE_DIR /
#                            HIFI_VU_SKINS_DIR (a local catalogue signed with
#                            a test key); without it the store is empty
#   MOCK_VU=0                start with the VU meters off
#   MOCK_NP_ANIMATION=cd     the Now Playing animation (none, cd, cdfront,
#                            vinyl, cassette) shown with the VU meters off
#   MOCK_ANIM_STORE=1        the animation store and the animation choice run
#                            on the real api_server.py code: configure it with
#                            HIFI_ANIM_STORE_URL / HIFI_ANIM_STORE_PUBKEY /
#                            HIFI_ANIM_STORE_DIR / HIFI_ANIM_STORE_STATE_DIR
#                            (the kiosk in the chroot must see the same
#                            folder as its /var/lib/hifi-player/anim-scenes)
NP_ANIMATIONS = ("none", "cd", "cdfront", "vinyl", "cassette")
VU_API = None
if os.environ.get("MOCK_VU_STORE"):
    sys.path.insert(0, os.path.join(HERE, "..", ".."))
    import api_server as VU_API
    VU_API.VU_STYLE_FILE = os.environ.get("MOCK_VU_STYLE_FILE", "/tmp/hifi-mock-vu-style")
    VU_API.VU_STORE_FIRST_CHECK = 0
ANIM_API = None
if os.environ.get("MOCK_ANIM_STORE"):
    sys.path.insert(0, os.path.join(HERE, "..", ".."))
    import api_server as ANIM_API
    ANIM_API.NOWPLAYING_ANIMATION_FILE = os.environ.get("MOCK_NP_ANIMATION_FILE", "/tmp/hifi-mock-np-animation")
    ANIM_API.ANIM_STORE_FIRST_CHECK = 0
if os.environ.get("MOCK_LONG_QUEUE"):
    QUEUE = [(f"{t[0]} ({i + 1})", t[1], t[2]) for i in range(8) for t in QUEUE]
#   MOCK_PLAYERS=1           two more players on the server (a phone and
#                            "Cucina"), each with its own now playing, for
#                            the player picker
SHARED_LMS = float(os.environ.get("MOCK_SHARED_LMS", "0") or 0)
EXTRA_PLAYERS = [
    {"playerid": "de:ad:be:ef:00:01", "name": "iPhone di Ale", "ip": "192.168.0.23:51234", "connected": 1},
    {"playerid": "de:ad:be:ef:00:02", "name": "Cucina", "ip": "192.168.0.31:3483", "connected": 1},
] if os.environ.get("MOCK_PLAYERS") else []
# what the other players are doing (status for a playerid that is not ours)
OTHER = {
    "de:ad:be:ef:00:01": {"title": "Blue in Green", "artist": "Miles Davis", "album": "Kind of Blue", "volume": 22, "mode": "play"},
    "de:ad:be:ef:00:02": {"title": "Re", "artist": "Nils Frahm", "album": "Felt", "volume": 65, "mode": "pause"},
}
PHONE = {"playerid": "de:ad:be:ef:00:01", "name": "iPhone di Ale", "ip": "192.168.0.23:51234", "connected": 1}
OWN = {"playerid": "aa:bb:cc:dd:ee:ff", "name": "Osmium", "ip": "127.0.0.1:41234", "connected": 1}
# favourites (Favorites plugin) and the library scan, as Lyrion answers
# them; MOCK_SCAN=N makes a rescan last N s
FAVS = [
    {"id": "0", "name": "Radio Paradise", "url": "http://stream.radioparadise.com/flac", "isaudio": 1, "hasitems": 0, "type": "audio"},
    {"id": "1", "name": "TOTO IV", "url": "db:album.title=TOTO%20IV&contributor.name=TOTO", "isaudio": 1, "hasitems": 0, "type": "playlist"},
    {"id": "2", "name": "Serate", "isaudio": 0, "hasitems": 1, "type": "link"},
]
MUTE = {"on": 0}
SCAN = {"until": 0.0, "last": T0 - 3600 * 5}
SCAN_SECS = float(os.environ.get("MOCK_SCAN", "12") or 12)
GENRES = ["Rock", "Jazz", "Classica", "Elettronica", "Ambient"]
YEARS = [1982, 1973, 1985, 2001, 2019, 0]

def players_now():
    if not SHARED_LMS:
        return [OWN] + EXTRA_PLAYERS
    own = dict(OWN, ip="192.168.0.40:41234")
    return [PHONE, own] if time.time() - T0 >= SHARED_LMS else [PHONE]

def status_now():
    if STATE["mode"] == "play":
        STATE["time"] = min(STATE["duration"], STATE["time"] + (time.time() - T0) % 1 * 0)
    return STATE

# Le tre specie di voce che restituisce un plugin, per provare il menu a
# pressione lunga: musica da suonare, un contenitore di musica (album, playlist)
# e un nodo di navigazione. Lyrion mette presetParams.favorites_url solo sulle
# prime due, ed e' da li' che la UI capisce quali sono musica.
def plugin_item(cmd, i):
    kind = i % 3
    o = {"id": f"{cmd}.{i}", "name": f"{cmd} voce {i + 1}",
         "hasitems": 0 if kind == 0 else 1,
         "isaudio": 1 if kind == 0 else 0,
         "type": "audio" if kind == 0 else "link"}
    if kind == 0:
        o["url"] = f"http://mock/{cmd}/{i}.mp3"
        o["presetParams"] = {"favorites_url": o["url"], "favorites_title": o["name"]}
    elif kind == 1:
        o["presetParams"] = {"favorites_url": f"{cmd}://album/{i}", "favorites_title": o["name"]}
    return o


# La stessa voce in forma di menu Jive: si porta dietro le azioni, `add` accoda
# e `add-hold` fa suonare dopo.
def menu_item(cmd, i):
    it = {"id": f"{cmd}.{i}", "text": f"{cmd} voce {i + 1}",
          "actions": {"go": {"cmd": [cmd, "items"], "params": {"item_id": f"{cmd}.{i}"}}}}
    if i % 3 != 2:
        it["actions"]["add"] = {"cmd": [cmd, "playlist", "add"], "params": {"item_id": f"{cmd}.{i}"}}
        it["actions"]["add-hold"] = {"cmd": [cmd, "playlist", "insert"], "params": {"item_id": f"{cmd}.{i}"}}
        it["presetParams"] = {"favorites_url": f"{cmd}://item/{i}", "favorites_title": it["text"]}
    return it


def rpc(player, params):
    cmd = params[0] if params else ""
    r = {}
    # the transport commands, in the log (to check what the UI sends)
    if cmd in ("play", "pause", "stop", "power") or params[:2] == ["playlist", "index"] or (params[:2] == ["mixer", "volume"] and params[2:3] != ["?"]):
        print("mock: player", player, params, flush=True)
    if cmd == "players":
        pl = players_now()
        r = {"count": len(pl), "players_loop": pl}
    elif cmd == "status":
        if len(params) > 1 and params[1] == "-" and player in OTHER:
            # a player that left the server answers nothing, like Lyrion does
            if not any(p["playerid"] == player for p in players_now()):
                return {}
            o = OTHER[player]
            owner = next((p["name"] for p in players_now() if p["playerid"] == player), player)
            r = {"player_name": owner, "mode": o["mode"], "time": 42.0, "duration": 300.0, "mixer volume": o["volume"],
                 "playlist_cur_index": 0, "playlist_tracks": 1, "playlist repeat": 0, "playlist shuffle": 0, "will_sleep_in": 0,
                 "playlist_loop": [{"id": 2001, "title": o["title"], "artist": o["artist"], "album": o["album"], "coverid": "1001",
                                    "bitrate": "1411kbps", "type": "flc", "samplesize": 16, "samplerate": 44100, "duration": 300.0, "remote": 0}]}
        elif len(params) > 1 and params[1] == "-" and STATE.get("radio"):
            # an internet radio, as Lyrion reports one (radio.de stream on the Dell,
            # 2026-09-18): no album, no duration, the station in remote_title
            rd = STATE["radio"]
            owner = next((p["name"] for p in players_now() if p["playerid"] == player), "Osmium")
            r = {"player_name": owner, "mode": STATE["mode"], "time": STATE["time"], "mixer volume": STATE["volume"],
                 "power": STATE["power"], "remote": 1, "current_title": " - ".join(x for x in (rd.get("artist"), rd.get("title")) if x),
                 "playlist_cur_index": "0", "playlist_tracks": 1, "playlist repeat": 0, "playlist shuffle": 0, "will_sleep_in": 0,
                 "playlist_loop": [{"id": "-94761577295040", "title": rd.get("title", ""), "artist": rd.get("artist", ""),
                                    "remote_title": rd.get("station", ""), "coverid": "-94761577295040", "type": "mp3",
                                    "url": rd.get("url", "https://ella.stream46.radiohost.de/ella-piano-trios_mp3-192"),
                                    "duration": "0", "remote": 1, "bitrate": "192kbps"}]}
        elif len(params) > 1 and params[1] == "-":
            t = QUEUE[STATE["index"] % len(QUEUE)]
            owner = next((p["name"] for p in players_now() if p["playerid"] == player), "Osmium")
            r = {"player_name": owner, "mode": STATE["mode"], "time": STATE["time"], "duration": STATE["duration"], "mixer volume": STATE["volume"],
                 "power": STATE["power"],
                 "playlist_cur_index": STATE["index"], "playlist_tracks": len(QUEUE), "playlist repeat": STATE["repeat"],
                 "playlist shuffle": STATE["shuffle"], "will_sleep_in": STATE["sleep"],
                 "playlist_loop": [{"id": 1001 + STATE["index"], "title": t[0], "artist": t[1], "album": t[2], "coverid": "1001", "album_id": 1 + STATE["index"] % 24, "artist_id": 1,
                                    "url": "file:///srv/music/%d.dsf" % STATE["index"],
                                    "bitrate": "2822kHz", "type": "dsf", "samplesize": 1, "samplerate": 2822400, "duration": STATE["duration"], "remote": 0}]}
        else:
            r = {"playlist_cur_index": STATE["index"], "playlist_tracks": len(QUEUE),
                 "playlist_loop": [{"id": 1001 + i, "title": q[0], "artist": q[1], "album": q[2], "playlist index": i} for i, q in enumerate(QUEUE)]}
    elif cmd == "playerpref":
        # ["playerpref", name, "?"] reads, ["playerpref", name, value] writes (as Lyrion)
        if len(params) > 2 and params[2] != "?":
            STATE["prefs"][params[1]] = str(params[2])
        r = {"_p2": STATE["prefs"].get(params[1], "0")}
    elif player in OTHER and cmd in ("play", "pause", "mixer"):
        o = OTHER[player]
        if cmd == "play": o["mode"] = "play"
        elif cmd == "pause": o["mode"] = "pause" if params[1:2] == ["1"] else "play"
        else: o["volume"] = int(params[2])
    elif cmd == "play": STATE["mode"] = "play"; STATE["power"] = 1          # play turns the player on, as Lyrion
    elif cmd == "pause": STATE["mode"] = "pause" if params[1:2] == ["1"] else "play"
    elif cmd == "stop": STATE["mode"] = "stop"; STATE["time"] = 0.0
    elif cmd == "power":
        if params[1:2] and params[1] != "?":
            STATE["power"] = int(params[1])
            if not STATE["power"]: STATE["mode"] = "stop"
        r = {"_power": STATE["power"]}
    elif cmd == "time": STATE["time"] = float(params[1])
    elif cmd == "mixer":
        if params[1] == "muting":
            if params[2] == "?": r = {"_muting": MUTE["on"]}
            else: MUTE["on"] = (1 - MUTE["on"]) if params[2] == "toggle" else int(params[2])
        elif params[2] != "?": STATE["volume"] = int(params[2])
    elif cmd == "sleep": STATE["sleep"] = int(params[1])
    elif cmd == "playlist":
        sub = params[1]
        if sub == "index":
            v = params[2]
            STATE["index"] = (STATE["index"] + int(v)) % len(QUEUE) if v[0] in "+-" else int(v)
            STATE["time"] = 0.0                    # another track starts from the beginning
        elif sub == "shuffle": STATE["shuffle"] = int(params[2])
        elif sub == "repeat": STATE["repeat"] = int(params[2])
        elif sub == "delete": QUEUE.pop(int(params[2]))
        elif sub == "move": QUEUE.insert(int(params[3]), QUEUE.pop(int(params[2])))
        elif sub == "clear": QUEUE.clear()
        elif sub == "save": r = {"__playlist_id": 9}
        elif sub == "play":
            STATE["mode"] = "play"
            print("mock: playlist play", params[2:], flush=True)
    elif cmd == "musicartistinfo":
        r = {"lyrics": "Meet you all the way<br>Rosanna, yeah<br><br>All I wanna do when I wake up in the morning<br>is see your eyes<br>" * 8}
    elif cmd == "artists":
        def arg(k): return next((p[len(k):] for p in params if isinstance(p, str) and p.startswith(k)), None)
        names = ARTISTS[-4:] if any(p == "role_id:COMPOSER" for p in params) else ARTISTS
        if arg("artist_id:"): names = [a for a in ARTISTS if str(ARTISTS.index(a) + 1) == arg("artist_id:")]
        r = {"artists_loop": [{"id": ARTISTS.index(a) + 1, "artist": a, "favorites_url": "db:contributor.name=" + a} for a in names], "count": len(names)}
    elif cmd == "roles":
        # the artist page asks which roles an artist has: albums, and some as composer
        def arg(k): return next((p[len(k):] for p in params if isinstance(p, str) and p.startswith(k)), None)
        aid = int(arg("artist_id:") or 0)
        roles = [{"role_id": 1, "role_name": "ARTIST"}] + ([{"role_id": 2, "role_name": "COMPOSER"}] if aid > len(ARTISTS) - 4 else []) + [{"role_id": 6, "role_name": "TRACKARTIST"}]
        r = {"roles_loop": roles, "count": len(roles)}
    elif cmd == "albums":
        def arg(k): return next((p[len(k):] for p in params if isinstance(p, str) and p.startswith(k)), None)
        aid, gid, year, sort, alid, role = arg("artist_id:"), arg("genre_id:"), arg("year:"), arg("sort:"), arg("album_id:"), arg("role_id:") or ""
        rows = [(i, al, ar, arid) for i, al, ar, arid in ALBUMS if not aid or str(arid) == aid]
        if alid: rows = [x for x in ALBUMS if str(x[0]) == alid]
        if gid: rows = [x for x in rows if x[0] % len(GENRES) == int(gid) - 1]
        if year: rows = [x for x in rows if YEARS[x[0] % len(YEARS)] == int(year)]
        if sort == "new": rows = list(reversed(rows))[:6]
        if aid and role:
            # ARTIST: the artist's own albums; COMPOSER / TRACKARTIST: two others each
            if "ARTIST" in role.split(","): pass
            elif role == "COMPOSER": rows = [x for x in ALBUMS if x[3] != int(aid)][:2]
            elif role == "TRACKARTIST": rows = [x for x in ALBUMS if x[3] != int(aid)][2:5]
            else: rows = []
        if sort == "yearalbum": rows = sorted(rows, key=lambda x: YEARS[x[0] % len(YEARS)])
        # album 3 has no cover (artwork_track_id missing), album 5 is on two discs, 7 is a compilation
        loop = [{"id": i, "album": al, "artist": ar, "artist_id": arid, "artists": ar, "artist_ids": str(arid), "year": YEARS[i % len(YEARS)],
                 "disccount": 2 if i == 5 else 1, "compilation": 1 if i == 7 else 0, "release_type": "ALBUM",
                 **({} if i == 3 else {"artwork_track_id": str(1000 + i)}),
                 "favorites_url": "db:album.title=%s&contributor.name=%s" % (al, ar)} for i, al, ar, arid in rows]
        r = {"albums_loop": loop, "count": len(loop)}
    elif cmd == "genres":
        r = {"genres_loop": [{"id": i + 1, "genre": g, "favorites_url": "db:genre.name=" + g} for i, g in enumerate(GENRES)], "count": len(GENRES)}
    elif cmd == "years":
        r = {"years_loop": [{"year": y, "favorites_url": "db:year.id=%d" % y} for y in sorted(YEARS, reverse=True)], "count": len(YEARS)}
    elif cmd == "search":
        term = next((p[5:] for p in params if isinstance(p, str) and p.startswith("term:")), "").lower()
        arts = [{"contributor_id": i + 1, "contributor": a} for i, a in enumerate(ARTISTS) if term in a.lower()]
        albs = [{"album_id": i, "album": al} for i, al, ar, arid in ALBUMS if term in al.lower()][:8]
        trks = [{"track_id": 2000 + i, "track": t} for i, t in enumerate(["Rosanna", "Africa", "Hold the Line", "Time", "Money", "Rosanna (live)"]) if term in t.lower()]
        r = {"contributors_loop": arts, "albums_loop": albs, "tracks_loop": trks, "contributors_count": len(arts), "albums_count": len(albs), "tracks_count": len(trks), "count": len(arts) + len(albs) + len(trks)}
    elif cmd == "titles":
        alid = next((p[9:] for p in params if isinstance(p, str) and p.startswith("album_id:")), None)
        al = next((x for x in ALBUMS if str(x[0]) == alid), None) if alid else None
        if al:
            # an album's tracks with the per-role tags (A + S) and the format of the files
            i, name, ar, arid = al
            n = 12 if i == 5 else 8
            loop = []
            for k in range(n):
                disc = 1 + (k >= 6) if i == 5 else 1
                t = {"id": 5000 + i * 100 + k, "title": f"Brano {k + 1} di {name}", "tracknum": (k % 6) + 1 if i == 5 else k + 1, "disc": disc,
                     "duration": 180 + k * 23, "artist": ar, "artist_ids": str(arid), "album_id": i, "type": "flc", "samplesize": 24, "samplerate": 96000,
                     "url": "file:///srv/music/%d/%d.flac" % (i, k), "composer": "Ludovico Einaudi" if k < 3 else "Nils Frahm", "composer_ids": "4" if k < 3 else "10"}
                if i == 7:
                    other = ARTISTS[(k + 2) % len(ARTISTS)]
                    t.update({"trackartist": other, "trackartist_ids": str(ARTISTS.index(other) + 1)})
                if k == 1:
                    t.update({"conductor": "Beethoven", "conductor_ids": "12"})
                loop.append(t)
            r = {"titles_loop": loop, "count": len(loop)}
        else:
            r = {"titles_loop": [{"id": 2000 + i, "title": f"Brano {i + 1}", "artist": "Toto", "duration": 200 + i * 7, "album_id": (i % 24) + 1, "artist_id": 1, "url": "file:///srv/music/toto/%d.flac" % i, "favorites_url": "file:///srv/music/toto/%d.flac" % i} for i in range(14)]}
    elif cmd == "musicfolder":
        r = {"folder_loop": [{"id": 1, "filename": "Musica", "type": "folder"}, {"id": 2, "filename": "USB", "type": "folder"}, {"id": 3, "filename": "brano.flac", "type": "track"}]}
    elif cmd == "playlists":
        if params[1:2] == ["tracks"]:
            r = {"playlisttracks_loop": [{"id": 3000 + i, "title": f"Playlist brano {i + 1}", "artist": "Vari", "url": "file:///srv/music/pl/%d.flac" % i} for i in range(6)]}
        elif params[1:2] == ["rename"]:
            new = next((p[8:] for p in params if isinstance(p, str) and p.startswith("newname:")), "")
            if new.lower() == "serata": r = {"overwritten_playlist_id": 2}
            elif not any(p == "dry_run:1" for p in params): print("mock: playlist renamed", params[2:], flush=True)
        elif params[1:2] in (["delete"], ["edit"]):
            print("mock: playlists", params[1:], flush=True)
        else:
            r = {"playlists_loop": [{"id": 1, "playlist": "Preferiti", "url": "file:///srv/music/playlist/preferiti.m3u"}, {"id": 2, "playlist": "Serata", "url": "file:///srv/music/playlist/serata.m3u"}]}
    elif cmd == "favorites":
        sub = params[1] if len(params) > 1 else ""
        def arg(k): return next((p[len(k):] for p in params if isinstance(p, str) and p.startswith(k)), None)
        if sub == "playlist":
            print("mock: favorites", params[1:], flush=True)
        elif sub == "items":
            r = {"loop_loop": [dict(f) for f in FAVS], "count": len(FAVS)}
        elif sub == "exists":
            what = params[2] if len(params) > 2 else ""
            idx = next((f["id"] for f in FAVS if f.get("url") == what or (what.isdigit() and f.get("url", "").endswith("/%d.dsf" % (int(what) - 1001)))), None)
            r = {"exists": 1 if idx is not None else 0, "index": idx or 0}
        elif sub == "add":
            FAVS.append({"id": str(len(FAVS)), "name": arg("title:") or arg("url:"), "url": arg("url:"), "isaudio": 1, "hasitems": 0, "type": arg("type:") or "audio"})
            r = {"count": 1}
        elif sub == "delete":
            i = arg("item_id:"); FAVS[:] = [f for f in FAVS if f["id"] != i]
            for n, f in enumerate(FAVS): f["id"] = str(n)
        elif sub == "rename":
            i = arg("item_id:")
            for f in FAVS:
                if f["id"] == i: f["name"] = arg("title:")
        elif sub == "move":
            a, b = int(arg("from_id:")), int(arg("to_id:"))
            FAVS.insert(b, FAVS.pop(a))
            for n, f in enumerate(FAVS): f["id"] = str(n)
    elif cmd == "info" and params[1:2] == ["total"]:
        r = {"_" + params[2]: {"albums": 312, "artists": 148, "genres": len(GENRES), "songs": 4021, "duration": 986543}[params[2]]}
    elif cmd == "rescanprogress":
        r = {"rescan": 1, "steps": "directory", "directory": int(100 * (1 - (SCAN["until"] - time.time()) / SCAN_SECS))} if time.time() < SCAN["until"] else {"rescan": 0}
    elif cmd == "abortscan":
        SCAN["until"] = 0.0
    elif cmd == "radios":
        r = {"radioss_loop": [{"cmd": "local", "name": "Radio locali", "icon": "/plugins/cache/icons/local.png"}, {"cmd": "tunein", "name": "TuneIn", "icon": "/plugins/cache/icons/tunein.png"}]}
    elif cmd == "apps":
        r = {"appss_loop": [{"cmd": "qobuz", "name": "Qobuz", "icon": "/plugins/cache/icons/qobuz.png"}]}
    elif cmd == "menu":
        r = {"item_loop": [
            {"id": "myMusic", "node": "home", "text": "La mia musica", "actions": {"go": {"cmd": ["myMusic"]}}},
            {"id": "radios", "node": "home", "text": "Radio", "actions": {"go": {"cmd": ["radios"]}}},
            {"id": "search", "node": "home", "text": "Cerca", "weight": 3, "actions": {"go": {"cmd": ["search", "items"], "params": {"menu": 1, "search": "__TAGGEDINPUT__"}}}, "input": {"len": 1}},
            {"id": "favorites", "node": "home", "text": "Preferiti", "weight": 2, "actions": {"go": {"cmd": ["favorites", "items"], "params": {"menu": "favorites"}}}},
            {"id": "qobuz", "node": "home", "text": "Qobuz", "weight": 5, "icon": "/plugins/cache/icons/qobuz.png", "actions": {"go": {"cmd": ["qobuz", "items"], "params": {"menu": "qobuz"}}}},
        ]}
    elif cmd in ("local", "tunein", "qobuz", "favorites", "search"):
        # <plugin> playlist add|insert|play item_id:… — quello che manda il menu
        # a pressione lunga dentro un'app
        if params[1:2] == ["playlist"]:
            print("mock:", cmd, params[1:], flush=True)
        else:
            r = {"loop_loop": [plugin_item(cmd, i) for i in range(9)],
                 "item_loop": [menu_item(cmd, i) for i in range(9)]}
    elif cmd == "playlistcontrol":
        pass
    elif cmd == "serverstatus":
        scanning = time.time() < SCAN["until"]
        if not scanning and SCAN["until"] > 0: SCAN["last"] = SCAN["until"]; SCAN["until"] = 0.0
        r = {"players_loop": [{"playerid": "aa:bb:cc:dd:ee:ff", "name": "Osmium"}, {"playerid": "11:22:33:44:55:66", "name": "Cucina"}, {"playerid": "77:88:99:aa:bb:cc", "name": "Camera"}],
             "lastscan": int(SCAN["last"]), "rescan": 1 if scanning else 0}
        if scanning:
            r.update({"progressname": "Cartelle", "progressdone": int(SCAN_SECS - (SCAN["until"] - time.time())), "progresstotal": int(SCAN_SECS)})
    elif cmd == "alarms":
        r = {"alarms_loop": [{"id": "a1", "time": 7 * 3600 + 30 * 60, "enabled": 1}, {"id": "a2", "time": 9 * 3600, "enabled": 0}]}
    elif cmd == "rescan":
        SCAN["until"] = time.time() + SCAN_SECS
    elif cmd == "alarm" or cmd == "sync":
        pass
    return {"id": 1, "method": "slim.request", "params": [player, params], "result": r}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f: b = f.read()
        except OSError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); port = self.server.server_address[1]
        if port == 9000:
            if u.path.startswith("/music/"): return self._file(COVER, "image/jpeg")
            if u.path.startswith("/plugins/"): return self._file(COVER, "image/png")
            return self._json({"ok": True})
        if port == 8000 and u.path in ("/anim_store", "/nowplaying_animation"):
            if ANIM_API is not None:
                if u.path == "/anim_store":
                    return self._json(ANIM_API.get_anim_store(summary="summary=1" in (u.query or "")))
                return self._json(ANIM_API.get_nowplaying_animation())
            if u.path == "/anim_store":
                return self._json({"new": 0, "updates": 0} if "summary=1" in (u.query or "") else
                                  {"animations": [], "checking": False, "busy": False, "error": None, "checked": 0})
        if port == 8000 and u.path in ("/vu_store", "/vu_style"):
            if VU_API is None:
                if u.path == "/vu_store":
                    return self._json({"new": 0, "updates": 0} if "summary=1" in (u.query or "") else
                                      {"skins": [], "checking": False, "busy": False, "error": None, "checked": 0})
            elif u.path == "/vu_store":
                return self._json(VU_API.get_vu_store(summary="summary=1" in (u.query or "")))
            else:
                return self._json(VU_API.get_vu_style())
        if port == 8000:
            table = {
                "/vu_meter": {"enabled": STATE["vu"]}, "/nowplaying_autoexpand": {"seconds": STATE["autoexpand"]},
                "/nowplaying_animation": {"animation": STATE["np_animation"], "choices": list(NP_ANIMATIONS)},
                "/vu_style": {"style": STATE["vu_style"], "styles": [{"id": "classic", "name": {"en": "Classic", "it": "Classico"}},
                                                                  {"id": "modulometer", "name": {"en": "Modulometer", "it": "Modulometro"}},
                                                                  {"id": "amber", "name": {"en": "Amber", "it": "Ambra"}},
                                                                  {"id": "ice-blue", "name": {"en": "Ice Blue", "it": "Blu ghiaccio"}},
                                                                  {"id": "exposed", "name": {"en": "Exposed", "it": "A vista"}},
                                                                  {"id": "panoramic", "name": {"en": "Panoramic", "it": "Panoramico"}}]},
                "/update/status": STATE["ota"], "/boot_mode": {"mode": "live"}, "/provision_status": {"pending": False, "completed": True, "networks": [{"ssid": "CasaWiFi", "security": "WPA2", "signal": 78, "band": "2.4"}, {"ssid": "CasaWiFi", "security": "WPA2", "signal": 64, "band": "5"}, {"ssid": "Ospiti", "security": "", "signal": 40, "band": "2.4"}]},
                "/player_name": {"name": "Osmium"}, "/ui_language": {"lang": STATE["lang"]},
                "/display_mode": {"mode": STATE["display_mode"]}, "/ui_resolution": {"mode": STATE["ui_resolution"]}, "/ui_refresh": {"supported": True, "mode": STATE["ui_refresh"]},
                "/network_status": {"connected": True, "type": "wired", "ssid": None, "ip": "192.168.0.133", "device": "eth0"},
                "/connectivity": {"state": STATE["net"], "type": STATE["net_type"], "ssid": "CasaWiFi" if STATE["net_type"] == "wireless" else None,
                                  "ip": None if STATE["net"] == "offline" and STATE["net_type"] == "none" else "192.168.0.133",
                                  "device": None if STATE["net_type"] == "none" else ("wlan0" if STATE["net_type"] == "wireless" else "eth0"),
                                  "gateway": "192.168.0.1", "router": STATE["net"] != "offline", "at": int(time.time())},
                "/network_info": {"hostname": "osmium", "ip": "192.168.0.133", "netmask": "255.255.255.0"},
                "/system_info": {"hostname": "osmium", "platform": "Debian 13", "arch": "x86_64", "local_ip": "192.168.0.133", "version": "2.5.24-dev.2",
                                 "network_interfaces": [{"name": "eth0", "address": "192.168.0.133", "active": True}, {"name": "wlan0", "address": "192.168.0.140", "active": False}]},
                "/pointer_status": {"enabled": STATE["pointer"], "available": True}, "/ssh_status": {"enabled": STATE["ssh"], "available": True, "active": STATE["ssh"]},
                "/player_enabled": {"enabled": STATE["player_enabled"]},
                "/lms_role": {"mode": STATE["lms_mode"], "host": STATE["lms_host"]}, "/timezone": {"timezone": STATE["tz"]},
                "/timezones": {"timezones": ["Europe/Rome", "Europe/London", "Europe/Berlin", "Europe/Paris", "UTC", "America/New_York", "Asia/Tokyo"]},
                "/device_name": {"name": STATE["device_name"]}, "/ota_channel": {"channel": STATE["ota_channel"], "channels": ["prod", "dev", "alpha"]},
                "/lyrion_channel": {"channel": STATE["lyrion_channel"]},
                "/lyrion_update/check": {"current": "9.0.2", "channels": {"release": {"version": "9.0.2"}, "nightly": {"version": "9.1.0~2026-08-25"}, "dev": {"version": "9.1.0"}}},
                "/lyrion_update/status": {"message": "", "percent": 0, "running": False},
                "/audio_devices": {"devices": [{"id": "default", "name": "System default"}, {"id": "hw:CARD=DAC,DEV=0", "name": "USB DAC"}, {"id": "hw:CARD=HDMI,DEV=0", "name": "HDMI"}], "current": STATE["audio"]},
                "/shell_account": {"username": STATE["shell_user"]}, "/wired_dhcp": {"dhcp": True},
                "/app_update/check": {"current": "2.5.24-dev.2", "latest": "2.5.24-dev.3", "update_available": True, "notes": "## 2.5.24-dev.3\n- UI nativa in Qt\n- correzioni varie\n" * 6},
                "/system_update/check": {"current": "2.5.24-dev.2", "latest": "2.5.24-dev.2", "update_available": False},
                "/os_update/check": {"current": "0055", "latest": "0055", "update_available": False},
                "/discover_lms": {"servers": [{"name": "NAS Lyrion", "ip": "192.168.0.50"}, {"name": "Osmium", "ip": "192.168.0.133"}]},
                "/install/status": STATE["install"],
                "/install/disks": {"disks": [{"path": "/dev/sda", "model": "Samsung SSD 870", "transport": "sata", "size": 500107862016}, {"path": "/dev/nvme0n1", "model": "WD Black SN770", "transport": "nvme", "size": 1000204886016}, {"path": "/dev/mmcblk0boot0", "model": "eMMC", "size": 4000000}]},
                # CasaWiFi sta su tutte e due le bande, come quasi ogni router di casa:
                # e' il caso che l'elenco deve saper distinguere.
                "/wifi_scan": {"networks": [{"ssid": "CasaWiFi", "security": "WPA2", "signal": 78, "band": "2.4", "saved": True}, {"ssid": "CasaWiFi", "security": "WPA2", "signal": 64, "band": "5", "saved": True}, {"ssid": "Ospiti", "security": "", "signal": 40, "band": "2.4"}, {"ssid": "Vicino", "security": "WPA2", "signal": 20, "band": "5"}]},
            }
            if u.path in table: return self._json(table[u.path])
            return self._json({"success": False, "error": "mock: " + u.path}, 404)
        if port == 8080:
            q = parse_qs(u.query)
            if u.path.startswith("/api/sources/") and u.path.endswith("/browse"):
                path = q.get("path", [""])[0].strip("/")
                return self._json({"success": True, "path": path, "parent": "/".join(path.split("/")[:-1]) if path else None,
                                   "dirs": ["Album", "Compilation", "Live"] if not path else ["Disco 1", "Disco 2"]})
            if u.path == "/api/local/browse":
                path = q.get("path", [""])[0] or "/srv/music"
                return self._json({"success": True, "path": path, "parent": os.path.dirname(path) if path != "/" else None,
                                   "dirs": ["Musica", "Playlist", "Import"] if path.count("/") < 3 else []})
            table = {
                "/api/sources": {"sources": [{"id": "usb-1", "type": "usb", "name": "KINGSTON", "mountpoint": "/media/usb/KINGSTON", "subpath": "", "mounted": True, "rw": True, "usage": {"free": 21000000000, "total": 32000000000}},
                                             {"id": "smb-1", "type": "smb", "name": "NAS", "server": "nas.local", "share": "musica", "mountpoint": "/mnt/smb/nas", "subpath": "flac", "mounted": True, "rw": False, "usage": {"free": 900000000000, "total": 4000000000000}},
                                             {"id": "local-1", "type": "local", "name": "Interno", "path": "/srv/music", "exists": True}]},
                "/api/usb": {"disks": [{"path": "/dev/sdc1", "label": "VECCHIA", "model": "SanDisk", "error": "fs sconosciuto", "fstype": "hfs+", "size": "16 GB", "needs_format": False}]},
                "/api/internal/disks": {"disks": [{"path": "/dev/sda", "model": "Samsung SSD 870", "size": 1000204886016, "adopted": False, "has_data": True, "confirm": "sda-870",
                                                    "partitions": [{"path": "/dev/sda1", "fstype": "ext4", "label": "dati"}, {"path": "/dev/sda2", "fstype": "ntfs", "label": "win"}]},
                                                   {"path": "/dev/mmcblk0boot0", "model": "eMMC", "size": 4000000, "partitions": []},
                                                   {"path": "/dev/sdb", "model": "WD Blue", "size": 2000398934016, "adopted": True, "has_data": True, "confirm": "sdb-wd", "partitions": [{"path": "/dev/sdb1", "fstype": "ext4", "label": "Musica"}]}]},
                "/api/playlistdir": {"path": STATE["pldir"], "default": "/srv/music/playlist", "is_default": STATE["pldir"] == "/srv/music/playlist"},
                "/api/lms_skin": {"skin": STATE["skin"]}, "/api/lms_skin_status": {"state": "idle", "message": ""},
                "/api/internal/smb": {"enabled": True, "host": "osmium", "ip": "192.168.0.133", "username": "osmium", "password": "segreto123", "shares": ["Musica", "Import"]},
                "/api/internal/format/status": STATE["fmt"],
            }
            if u.path == "/api/sources/smb/discover":
                # La ricerca vera impiega qualche secondo e la lista si riempie
                # mentre gira: qui si simula col tempo trascorso, se no la
                # schermata "sto cercando" non si vedrebbe mai.
                sc = STATE["smbscan"]
                el = time.time() - sc["t0"]
                hosts = sc["hosts"][:1 + int(el)]
                done = el >= len(sc["hosts"])
                return self._json({"success": True, "state": "done" if done else "running",
                                   "progress": 100 if done else min(95, int(el * 30)),
                                   "hosts": hosts, "tools": {"shares": True, "mdns": True}})
            if u.path.startswith("/api/meta/"): return self._json(*meta_get(u.path, q))
            if u.path == "/api/cd/info": return self._json(STATE["cd"])
            if u.path == "/api/cd/rip/status": return self._json(STATE["cdrip"])
            if u.path in table: return self._json(table[u.path])
            return self._json({"error": "mock"}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n) if n else b""
        u = urlparse(self.path); port = self.server.server_address[1]
        if port == 9000 and u.path == "/jsonrpc.js":
            req = json.loads(body or b"{}"); pl, params = req.get("params", ["", []])
            return self._json(rpc(pl, params))
        try: data = json.loads(body or b"{}")
        except Exception: data = {}
        if port == 8000 and ANIM_API is not None and (u.path.startswith("/anim_store") or u.path == "/nowplaying_animation"):
            fn = {"/anim_store/check": lambda: ANIM_API.anim_store_check(),
                  "/anim_store/install": lambda: ANIM_API.anim_store_install(data.get("id")),
                  "/anim_store/remove": lambda: ANIM_API.anim_store_remove(data.get("id")),
                  "/anim_store/seen": lambda: ANIM_API.anim_store_mark_seen(),
                  "/nowplaying_animation": lambda: ANIM_API.set_nowplaying_animation(data.get("animation"))}.get(u.path)
            if fn: return self._json(fn())
        if port == 8000 and VU_API is not None and (u.path.startswith("/vu_store") or u.path == "/vu_style"):
            fn = {"/vu_store/check": lambda: VU_API.vu_store_check(), "/vu_store/install": lambda: VU_API.vu_store_install(data.get("id")),
                  "/vu_store/remove": lambda: VU_API.vu_store_remove(data.get("id")), "/vu_store/seen": lambda: VU_API.vu_store_mark_seen(),
                  "/vu_style": lambda: VU_API.set_vu_style(data.get("style"))}.get(u.path)
            if fn: return self._json(fn())
        if port == 8000:
            if u.path == "/wifi_connect":
                time.sleep(1.0)                      # nmcli takes its time
                if os.environ.get("MOCK_WIFI_FAIL"):
                    return self._json({"success": False, "code": "network.connectFailed",
                                       "message": "Error: Connection activation failed: (7) Secrets were required, but not provided."})
                STATE["net"] = "internet"; STATE["net_type"] = "wireless"
                return self._json({"success": True, "message": "ok", "ip": "192.168.0.140"})
            if u.path == "/wired_dhcp":
                if os.environ.get("MOCK_WIRED_FAIL"):
                    return self._json({"success": False, "code": "network.cableNotConnected", "message": "no carrier"})
                STATE["net_type"] = "wired"
                return self._json({"success": True, "code": "network.wiredConnected", "ip": "192.168.0.133"})
            if u.path == "/vu_meter": STATE["vu"] = bool(data.get("enable", data.get("enabled", True)))
            if u.path == "/vu_style": STATE["vu_style"] = str(data.get("style") or "classic")
            if u.path == "/nowplaying_animation":
                kind = data.get("animation")
                if kind not in NP_ANIMATIONS:
                    return self._json({"success": False, "error": "unknown animation"}, 400)
                STATE["np_animation"] = kind
                return self._json({"success": True, "animation": kind})
            if u.path == "/nowplaying_autoexpand": STATE["autoexpand"] = int(data.get("seconds", 0))
            if u.path == "/ui_language": STATE["lang"] = data.get("lang", "en")
            if u.path == "/display_mode": STATE["display_mode"] = data.get("mode", "gui")
            if u.path == "/ui_resolution": STATE["ui_resolution"] = data.get("mode", "auto")
            if u.path == "/ui_refresh": STATE["ui_refresh"] = data.get("mode", "native")
            if u.path == "/pointer_set": STATE["pointer"] = bool(data.get("enable", True))
            if u.path == "/ssh_set": STATE["ssh"] = bool(data.get("enable", False))
            if u.path == "/player_enabled": STATE["player_enabled"] = bool(data.get("enabled", True))
            if u.path == "/lms_role": STATE["lms_mode"] = data.get("mode", "local"); STATE["lms_host"] = data.get("host", "")
            if u.path == "/timezone": STATE["tz"] = data.get("timezone", "UTC")
            if u.path == "/device_name": STATE["device_name"] = data.get("name", "Osmium")
            if u.path == "/ota_channel": STATE["ota_channel"] = data.get("channel", "prod")
            if u.path == "/lyrion_channel": STATE["lyrion_channel"] = data.get("channel", "release")
            if u.path == "/set_audio_device": STATE["audio"] = data.get("device", "default")
            if u.path == "/shell_account": STATE["shell_user"] = data.get("username", "")
            if u.path == "/install/start":
                STATE["install"] = {"state": "running", "message": "Copying system…", "progress": 20}
                threading.Timer(5.0, lambda: STATE.__setitem__("install", {"state": "done", "message": "", "progress": 100})).start()
            if u.path == "/mock/cd": STATE["cd"] = data
            if u.path == "/mock/ota": STATE["ota"] = data
            if u.path == "/mock/radio":            # {"title","artist","station"} plays a radio, {} goes back
                STATE["radio"] = data or None
            if u.path == "/mock/track":            # {"duration": s, "time": s}: another track length
                for k in ("duration", "time"):
                    if k in data: STATE[k] = float(data[k])
        if port == 8080:
            if u.path == "/api/pair/token": return self._json({"token": "abc123def456"})
            if u.path == "/api/sources/smb/discover":
                STATE["smbscan"]["t0"] = time.time()
                return self._json({"success": True, "state": "running"}, 202)
            if u.path == "/api/sources/smb/shares":
                # 192.168.0.60 chiede le credenziali: e' il ramo che serve per
                # provare il passo "accedi" senza un NAS vero.
                if data.get("server") == "192.168.0.60" and not data.get("username"):
                    return self._json({"success": True, "needs_auth": True, "shares": []})
                if data.get("server") == "192.168.0.60" and data.get("password") != "segreto":
                    return self._json({"success": False, "code": "msg.smbBadCredentials",
                                       "message": "Nome utente o password non corretti per questo dispositivo.",
                                       "detail": "session setup failed: NT_STATUS_LOGON_FAILURE"}, 400)
                return self._json({"success": True, "needs_auth": False,
                                   "shares": [{"name": "Musica", "comment": "La musica di casa"},
                                              {"name": "Backup", "comment": ""}]})
            if u.path == "/api/sources/smb/test":
                # "Musica" on SYNOLOGY (192.168.0.50) lists as a guest but only
                # opens with a login: the case where the folder, not the
                # device, asks for the password.
                if data.get("server") == "192.168.0.50" and data.get("share") == "Musica" and \
                        (data.get("username") != "casa" or data.get("password") != "segreto"):
                    return self._json({"success": False, "code": "msg.smbBadCredentials",
                                       "message": "Nome utente o password non corretti per questo dispositivo.",
                                       "detail": "tree connect failed: NT_STATUS_ACCESS_DENIED"}, 400)
                if data.get("share") == "Backup":
                    return self._json({"success": False, "code": "msg.smbNoSuchShare",
                                       "message": "Su quel dispositivo non c\u2019\u00e8 nessuna cartella condivisa con questo nome.",
                                       "detail": "tree connect failed: NT_STATUS_BAD_NETWORK_NAME"}, 400)
                return self._json({"success": True, "checked": True})
            if u.path == "/api/cd/rip":
                STATE["cdrip"] = {"state": "ripping", "message": "Copia in corso", "progress": 30, "track": 2, "total": len(data.get("tracks", []))}
                threading.Timer(6.0, lambda: STATE.__setitem__("cdrip", {"state": "done", "message": "Copia completata", "progress": 100})).start()
            if u.path == "/api/meta/settings":
                for k in ("online", "prefetch"):
                    if k in data: META["settings"][k] = bool(data[k])
                return self._json(meta_settings())
            if u.path == "/api/meta/cache/clear": META["seen"].clear(); return self._json({"ok": True})
            if u.path == "/api/meta/album/pin":
                print("mock: meta pin", data, flush=True)
                META["seen"].discard("album-%s" % data.get("album_id")); return self._json({"status": "pending"})
            if u.path == "/api/cd/eject": STATE["cd"] = {"no_disc": True}; STATE["cdrip"] = {"state": "idle"}
            if u.path == "/api/playlistdir": STATE["pldir"] = data.get("path", STATE["pldir"])
            if u.path == "/api/lms_skin": STATE["skin"] = data.get("skin", "unset")
            if u.path == "/api/internal/format":
                STATE["fmt"] = {"state": "running", "message": "Creazione del filesystem", "progress": 35}
                threading.Timer(4.0, lambda: STATE.__setitem__("fmt", {"state": "done", "message": "Fatto", "progress": 100})).start()
        return self._json({"success": True, "ok": True, "data": data})
    do_DELETE = do_POST
    do_PUT = do_POST

# /api/meta (sources_server + hifi_metadata.py): real-shaped answers saved from
# MusicBrainz/Wikipedia in tools/mock-meta/ (album-<id>.json, artist-<id>.json,
# person-<mbid>.json, candidates-<id>.json, settings.json). An id without its
# own file gets the first one of its kind. The first request for each entity
# answers "pending", like the real service while it looks things up.
#   MOCK_META=off      the service says "disabled"
#   MOCK_META=offline  the service says "offline"
#   MOCK_META=nomatch  nothing found for any album or artist
META_DIR = os.path.join(HERE, "mock-meta")
META = {"seen": set(), "settings": {"online": True, "prefetch": True}}
MOCK_META = os.environ.get("MOCK_META", "")

def meta_file(kind, key):
    try:
        names = sorted(f for f in os.listdir(META_DIR) if f.startswith(kind + "-") and f.endswith(".json"))
    except OSError:
        return None
    pick = "%s-%s.json" % (kind, key)
    if pick in names:
        names = [pick]
    # an id without its own file borrows one that has data (not the nomatch example)
    for name in names:
        with open(os.path.join(META_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
        if len(names) == 1 or d.get("status", "ok") == "ok":
            return d
    return None

def meta_settings():
    base = meta_file("settings", "") or {"cache": {"albums": 120, "artists": 48, "bytes": 3456789}, "prefetch_state": {"running": True, "done": 120, "total": 312}}
    return dict(base, **META["settings"])

def meta_get(path, q):
    one = lambda k: (q.get(k) or [""])[0]
    if path == "/api/meta/settings":
        return meta_settings(), 200
    if MOCK_META == "off":
        return {"status": "disabled"}, 200
    if MOCK_META == "offline":
        return {"status": "offline"}, 200
    kind, key = {"/api/meta/album": ("album", one("album_id")), "/api/meta/artist": ("artist", one("artist_id")),
                 "/api/meta/person": ("person", one("mbid")), "/api/meta/album/candidates": ("candidates", one("album_id")),
                 "/api/meta/appearances": ("appearances", one("mbid"))}.get(path, (None, None))
    if not kind:
        return {"status": "error", "message": "mock: " + path}, 404
    seen = "%s-%s" % (kind, key)
    if kind in ("album", "artist", "person") and seen not in META["seen"]:
        META["seen"].add(seen)
        return {"status": "pending"}, 200
    if MOCK_META == "nomatch" and kind != "appearances":
        return {"status": "nomatch", "candidates": []} if kind == "candidates" else {"status": "nomatch"}, 200
    d = meta_file(kind, key)
    if kind == "appearances" and d is None:
        # albums whose saved credits name this person
        albums = []
        for f in sorted(os.listdir(META_DIR)) if os.path.isdir(META_DIR) else []:
            if not f.startswith("album-"):
                continue
            with open(os.path.join(META_DIR, f), encoding="utf-8") as fh:
                a = json.load(fh)
            roles = [{"group": c.get("group"), "role": c.get("role"), "attr": c.get("attr", "")} for c in a.get("credits", [])
                     if any(p.get("mbid") == key for p in c.get("people", []))]
            if roles:
                albums.append({"album_id": a.get("album_id"), "title": (a.get("release") or {}).get("title", ""), "artist": (a.get("release") or {}).get("artist", ""), "roles": roles})
        return {"status": "ok", "albums": albums}, 200
    if d is None:
        return ({"status": "ok", "current": None, "pinned": None, "candidates": []} if kind == "candidates" else {"status": "nomatch"}), 200
    d = dict(d)
    if kind == "album": d["album_id"] = int(key or 0)
    if kind == "artist": d["artist_id"] = int(key or 0)
    return d, 200

def serve(port):
    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

async def vu_client(reader, writer):
    req = await reader.readuntil(b"\r\n\r\n")
    key = [l.split(b":", 1)[1].strip() for l in req.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
    acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
    writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
    t = 0.0
    try:
        while True:
            if STATE["mode"] == "play":
                l = max(0, min(100, 55 + 42 * math.sin(t / 0.26) + random.uniform(-12, 12)))
                r = max(0, min(100, 55 + 42 * math.sin(t / 0.23 + 1.1) + random.uniform(-12, 12)))
            else:
                l = r = 0
            payload = json.dumps({"levels_l": [l], "levels_r": [r]}).encode()
            writer.write(b"\x81" + bytes([len(payload)]) + payload)
            await writer.drain()
            await asyncio.sleep(0.05); t += 0.05
    except (ConnectionError, asyncio.CancelledError):
        pass

async def vu_main():
    srv = await asyncio.start_server(vu_client, "127.0.0.1", 9001)
    async with srv: await srv.serve_forever()

def ticker():
    while True:
        time.sleep(0.5)
        if STATE["mode"] == "play":
            STATE["time"] = STATE["time"] + 0.5
            if STATE["time"] >= STATE["duration"]: STATE["time"] = 0; STATE["index"] = (STATE["index"] + 1) % max(1, len(QUEUE))

if __name__ == "__main__":
    for p in (9000, 8000, 8080): threading.Thread(target=serve, args=(p,), daemon=True).start()
    threading.Thread(target=ticker, daemon=True).start()
    print("mock: lyrion :9000, api :8000, sources :8080, vu :9001", flush=True)
    asyncio.run(vu_main())
