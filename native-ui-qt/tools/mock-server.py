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
    "mode": "play", "time": 116.0, "duration": 330.0, "volume": 40, "index": 2, "shuffle": 0, "repeat": 0, "sleep": 0,
    "prefs": {"replayGainMode": "0", "transitionType": "0", "transitionDuration": "0", "digitalVolumeControl": "1"},
    "vu": True, "autoexpand": 0, "ota": {"state": "idle"}, "lang": "it",
    "display_mode": "gui", "ui_resolution": "auto", "ui_refresh": "native", "pointer": True, "ssh": False, "player_enabled": True,
    "lms_mode": "local", "lms_host": "", "tz": "Europe/Rome", "device_name": "Osmium", "ota_channel": "dev", "lyrion_channel": "release",
    "audio": "hw:CARD=DAC,DEV=0", "shell_user": "", "pldir": "/srv/music/playlist", "skin": "osmium", "fmt": {"state": "idle"},
    "install": {"state": "idle"}, "cd": {"no_disc": True}, "cdrip": {"state": "idle"},
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

def status_now():
    if STATE["mode"] == "play":
        STATE["time"] = min(STATE["duration"], STATE["time"] + (time.time() - T0) % 1 * 0)
    return STATE

def rpc(player, params):
    cmd = params[0] if params else ""
    r = {}
    if cmd == "players":
        r = {"count": 1, "players_loop": [{"playerid": "aa:bb:cc:dd:ee:ff", "name": "Osmium", "ip": "127.0.0.1:41234", "connected": 1}]}
    elif cmd == "status":
        if len(params) > 1 and params[1] == "-":
            t = QUEUE[STATE["index"] % len(QUEUE)]
            r = {"mode": STATE["mode"], "time": STATE["time"], "duration": STATE["duration"], "mixer volume": STATE["volume"],
                 "playlist_cur_index": STATE["index"], "playlist_tracks": len(QUEUE), "playlist repeat": STATE["repeat"],
                 "playlist shuffle": STATE["shuffle"], "will_sleep_in": STATE["sleep"],
                 "playlist_loop": [{"id": 1001 + STATE["index"], "title": t[0], "artist": t[1], "album": t[2], "coverid": "1001",
                                    "bitrate": "2822kHz", "type": "dsf", "samplesize": 1, "samplerate": 2822400, "duration": STATE["duration"], "remote": 0}]}
        else:
            r = {"playlist_cur_index": STATE["index"], "playlist_tracks": len(QUEUE),
                 "playlist_loop": [{"id": 1001 + i, "title": q[0], "artist": q[1], "album": q[2], "playlist index": i} for i, q in enumerate(QUEUE)]}
    elif cmd == "playerpref":
        r = {"_p2": STATE["prefs"].get(params[1], "0")}
    elif cmd == "play": STATE["mode"] = "play"
    elif cmd == "pause": STATE["mode"] = "pause" if params[1:2] == ["1"] else "play"
    elif cmd == "time": STATE["time"] = float(params[1])
    elif cmd == "mixer": STATE["volume"] = int(params[2])
    elif cmd == "sleep": STATE["sleep"] = int(params[1])
    elif cmd == "playlist":
        sub = params[1]
        if sub == "index":
            v = params[2]
            STATE["index"] = (STATE["index"] + int(v)) % len(QUEUE) if v[0] in "+-" else int(v)
        elif sub == "shuffle": STATE["shuffle"] = int(params[2])
        elif sub == "repeat": STATE["repeat"] = int(params[2])
        elif sub == "delete": QUEUE.pop(int(params[2]))
        elif sub == "move": QUEUE.insert(int(params[3]), QUEUE.pop(int(params[2])))
        elif sub == "clear": QUEUE.clear()
        elif sub == "save": r = {"__playlist_id": 9}
    elif cmd == "musicartistinfo":
        r = {"lyrics": "Meet you all the way<br>Rosanna, yeah<br><br>All I wanna do when I wake up in the morning<br>is see your eyes<br>" * 8}
    elif cmd == "artists":
        r = {"artists_loop": [{"id": i + 1, "artist": a} for i, a in enumerate(ARTISTS)], "count": len(ARTISTS)}
    elif cmd == "albums":
        aid = next((p.split(":")[1] for p in params if isinstance(p, str) and p.startswith("artist_id:")), None)
        loop = [{"id": i, "album": al, "artist": ar, "artwork_track_id": str(1000 + i)} for i, al, ar, arid in ALBUMS if not aid or str(arid) == aid]
        r = {"albums_loop": loop, "count": len(loop)}
    elif cmd == "titles":
        r = {"titles_loop": [{"id": 2000 + i, "title": f"Brano {i + 1}", "artist": "Toto", "duration": 200 + i * 7} for i in range(14)]}
    elif cmd == "musicfolder":
        r = {"folder_loop": [{"id": 1, "filename": "Musica", "type": "folder"}, {"id": 2, "filename": "USB", "type": "folder"}, {"id": 3, "filename": "brano.flac", "type": "track"}]}
    elif cmd == "playlists":
        if params[1:2] == ["tracks"]:
            r = {"playlisttracks_loop": [{"id": 3000 + i, "title": f"Playlist brano {i + 1}", "artist": "Vari"} for i in range(6)]}
        else:
            r = {"playlists_loop": [{"id": 1, "playlist": "Preferiti"}, {"id": 2, "playlist": "Serata"}]}
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
        r = {"loop_loop": [{"id": f"{cmd}.{i}", "name": f"{cmd} voce {i + 1}", "hasitems": 1 if i % 3 else 0, "isaudio": 0 if i % 3 else 1, "type": "link" if i % 3 else "audio"} for i in range(9)],
             "item_loop": [{"id": f"{cmd}.{i}", "text": f"{cmd} voce {i + 1}", "actions": {"go": {"cmd": [cmd, "items"], "params": {"item_id": f"{cmd}.{i}"}}}} for i in range(9)]}
    elif cmd == "playlistcontrol":
        pass
    elif cmd == "serverstatus":
        r = {"players_loop": [{"playerid": "aa:bb:cc:dd:ee:ff", "name": "Osmium"}, {"playerid": "11:22:33:44:55:66", "name": "Cucina"}, {"playerid": "77:88:99:aa:bb:cc", "name": "Camera"}],
             "rescan": 0, "progressdone": 0, "progresstotal": 0}
    elif cmd == "alarms":
        r = {"alarms_loop": [{"id": "a1", "time": 7 * 3600 + 30 * 60, "enabled": 1}, {"id": "a2", "time": 9 * 3600, "enabled": 0}]}
    elif cmd == "alarm" or cmd == "sync" or cmd == "rescan":
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
        if port == 8000:
            table = {
                "/vu_meter": {"enabled": STATE["vu"]}, "/nowplaying_autoexpand": {"seconds": STATE["autoexpand"]},
                "/update/status": STATE["ota"], "/boot_mode": {"mode": "live"}, "/provision_status": {"pending": False, "completed": True},
                "/player_name": {"name": "Osmium"}, "/ui_language": {"lang": STATE["lang"]},
                "/display_mode": {"mode": STATE["display_mode"]}, "/ui_resolution": {"mode": STATE["ui_resolution"]}, "/ui_refresh": {"supported": True, "mode": STATE["ui_refresh"]},
                "/network_status": {"connected": True, "type": "wired", "ssid": None, "ip": "192.168.0.133", "device": "eth0"},
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
                "/wifi_scan": {"networks": [{"ssid": "CasaWiFi", "security": "WPA2", "signal": 78}, {"ssid": "Ospiti", "security": "", "signal": 40}, {"ssid": "Vicino", "security": "WPA2", "signal": 20}]},
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
        if port == 8000:
            if u.path == "/vu_meter": STATE["vu"] = bool(data.get("enable", data.get("enabled", True)))
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
                if data.get("share") == "Backup":
                    return self._json({"success": False, "code": "msg.smbNoSuchShare",
                                       "message": "Su quel dispositivo non c\u2019\u00e8 nessuna cartella condivisa con questo nome.",
                                       "detail": "tree connect failed: NT_STATUS_BAD_NETWORK_NAME"}, 400)
                return self._json({"success": True, "checked": True})
            if u.path == "/api/cd/rip":
                STATE["cdrip"] = {"state": "ripping", "message": "Copia in corso", "progress": 30, "track": 2, "total": len(data.get("tracks", []))}
                threading.Timer(6.0, lambda: STATE.__setitem__("cdrip", {"state": "done", "message": "Copia completata", "progress": 100})).start()
            if u.path == "/api/cd/eject": STATE["cd"] = {"no_disc": True}; STATE["cdrip"] = {"state": "idle"}
            if u.path == "/api/playlistdir": STATE["pldir"] = data.get("path", STATE["pldir"])
            if u.path == "/api/lms_skin": STATE["skin"] = data.get("skin", "unset")
            if u.path == "/api/internal/format":
                STATE["fmt"] = {"state": "running", "message": "Creazione del filesystem", "progress": 35}
                threading.Timer(4.0, lambda: STATE.__setitem__("fmt", {"state": "done", "message": "Fatto", "progress": 100})).start()
        return self._json({"success": True, "ok": True, "data": data})
    do_DELETE = do_POST
    do_PUT = do_POST

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
