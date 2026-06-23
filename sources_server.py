#!/usr/bin/env python3
"""
HiFi Player — Music Sources manager.

A small self-contained web service (port 8080) that lets the user add music
sources to Lyrion Music Server from a browser on their phone/PC:

  * Local folders  → added directly to Lyrion's mediadirs
  * SMB shares     → mounted on /mnt/hifi-sources/<name> (cifs) then added
                     to mediadirs (Lyrion sees them as local folders)

State is persisted in /etc/hifi-sources.json; SMB shares are re-mounted when
this service starts (so they survive reboots without touching /etc/fstab).

Runs as root (needs mount.cifs and to restart Lyrion).
"""
from flask import Flask, jsonify, request, Response
import json
import os
import re
import glob
import time
import subprocess
import threading

app = Flask(__name__)

STATE_FILE = "/etc/hifi-sources.json"
MOUNT_ROOT = "/mnt/hifi-sources"
# Local music folders may only be added from these base directories. This
# keeps the (root-privileged) service from being pointed at arbitrary paths
# such as /etc or /root via the add-local-source API.
ALLOWED_LOCAL_ROOTS = ("/mnt", "/media", "/srv", "/home", MOUNT_ROOT)
LYRION_SERVICE = "lyrionmusicserver.service"
PREFS_GLOBS = [
    "/var/lib/squeezeboxserver/prefs/server.prefs",
    "/var/lib/lyrion*/prefs/server.prefs",
    "/var/lib/lyrionmusicserver/prefs/server.prefs",
]
# The appliance skips Lyrion's web setup wizard, so `playlistdir` is never set
# and "save queue as playlist" silently fails. We provision a writable folder.
DEFAULT_PLAYLISTDIR = "/var/lib/squeezeboxserver/playlists"

_lock = threading.Lock()


# ─────────────────────────── state ──────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"sources": []}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass


def _slug(*parts):
    s = "-".join(p for p in parts if p)
    # strip leading/trailing dots too, so a value like ".." can never survive
    # and turn os.path.join(MOUNT_ROOT, slug) into a path-traversal.
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_.") or "share"


def _field_ok(value):
    """True if `value` is safe to pass as a mount option / command argument.

    The SMB fields below are interpolated into mount(8) `-o` options and into
    the command argv; a comma, newline or a leading '-' would let a malicious
    value add arbitrary mount options or be parsed as a flag, so only allow a
    conservative character set and reject leading dashes.
    """
    v = "" if value is None else str(value)
    return bool(re.fullmatch(r"[^\x00-\x1f,]*", v)) and not v.startswith("-")


def _run(cmd, timeout=30):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ─────────────────────────── SMB mounting ───────────────────────────
def mount_smb(src):
    """Mount one SMB source. Returns (ok, message)."""
    server = src["server"].strip().strip("/")
    share = src["share"].strip().strip("/")
    username = src.get("username", "")
    password = src.get("password", "")
    for value in (server, share, username, password):
        if not _field_ok(value):
            return False, "Valore non valido in server/condivisione/credenziali"

    # The mountpoint is derived from user-supplied server/share; resolve it and
    # make sure it can never escape MOUNT_ROOT before we create or mount onto it.
    root = os.path.realpath(MOUNT_ROOT)
    mountpoint = os.path.realpath(src["mountpoint"])
    if mountpoint != root and not mountpoint.startswith(root + os.sep):
        return False, "mountpoint non valido"
    os.makedirs(mountpoint, exist_ok=True)

    if os.path.ismount(mountpoint):
        return True, "già montato"

    unc = f"//{server}/{share}"
    base_opts = f"uid=0,gid=0,iocharset=utf8,ro,file_mode=0644,dir_mode=0755"
    cred = ""
    if username:
        cred = f",username={username},password={password}"
    else:
        cred = ",guest"

    last = ""
    for vers in ("3.1.1", "3.0", "2.1", "1.0"):
        opts = f"{base_opts}{cred},vers={vers}"
        r = _run(["mount", "-t", "cifs", unc, mountpoint, "-o", opts])
        if r.returncode == 0:
            return True, f"montato (SMB {vers})"
        last = (r.stderr or r.stdout).strip()
    return False, last or "mount fallito"


def umount(mountpoint):
    if os.path.ismount(mountpoint):
        _run(["umount", "-l", mountpoint])


def remount_all():
    state = load_state()
    for src in state.get("sources", []):
        if src.get("type") == "smb":
            try:
                mount_smb(src)
            except Exception as e:
                print(f"[sources] remount failed for {src.get('name')}: {e}")


# ─────────────────────────── Lyrion mediadirs ───────────────────────
def _prefs_dir_from_service():
    """Read the real PREFSDIR from the lyrionmusicserver systemd unit."""
    try:
        r = _run(["systemctl", "show", LYRION_SERVICE, "-p", "Environment"])
        m = re.search(r"PREFSDIR=(\S+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None

def _find_prefs():
    candidates = []
    pd = _prefs_dir_from_service()
    if pd:
        candidates.append(os.path.join(pd, "server.prefs"))
    candidates += [
        "/var/lib/squeezeboxserver/prefs/server.prefs",
        "/var/lib/lyrionmusicserver/prefs/server.prefs",
    ]
    for pat in PREFS_GLOBS:
        candidates += glob.glob(pat)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

def _ensure_prefs():
    """Find server.prefs; if missing (fresh install), start Lyrion and wait
    for it to create the file on first run."""
    prefs = _find_prefs()
    if prefs:
        return prefs
    _run(["systemctl", "start", LYRION_SERVICE], timeout=30)
    for _ in range(20):  # up to ~40s
        time.sleep(2)
        prefs = _find_prefs()
        if prefs:
            return prefs
    return None


def _squeezebox_ids():
    """(uid, gid) of the squeezeboxserver user, or (None, None)."""
    try:
        import pwd
        ent = pwd.getpwnam("squeezeboxserver")
        return ent.pw_uid, ent.pw_gid
    except Exception:
        return None, None


def _provision_playlistdir(data):
    """Given the loaded prefs dict, make sure `playlistdir` points at an
    existing, writable folder (creating/chowning it). Returns the (possibly
    updated) dict and a bool telling whether anything changed."""
    cur = (data.get("playlistdir") or "").strip()
    if cur and os.path.isdir(cur) and os.access(cur, os.W_OK):
        return data, False
    target = cur or DEFAULT_PLAYLISTDIR
    uid, gid = _squeezebox_ids()
    try:
        os.makedirs(target, exist_ok=True)
        if uid is not None:
            os.chown(target, uid, gid)
    except Exception as e:
        print(f"[sources] playlistdir mkdir failed: {e}")
        return data, False
    data["playlistdir"] = target
    return data, True


def ensure_playlistdir():
    """Standalone provisioning used at service start (covers devices that were
    set up before this feature and never re-apply their sources). Idempotent:
    only stops/edits/starts Lyrion when the folder is missing/unset."""
    try:
        import yaml
    except Exception:
        return
    prefs = _find_prefs()
    if not prefs:
        return
    try:
        with open(prefs) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return
    data, changed = _provision_playlistdir(data)
    if not changed:
        return
    _run(["systemctl", "stop", LYRION_SERVICE], timeout=60)
    try:
        tmp = prefs + ".tmp"
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, prefs)
        uid, gid = _squeezebox_ids()
        if uid is not None:
            try:
                os.chown(prefs, uid, gid)
            except Exception:
                pass
    except Exception as e:
        print(f"[sources] playlistdir prefs write failed: {e}")
    finally:
        _run(["systemctl", "start", LYRION_SERVICE], timeout=60)
    print(f"[sources] playlistdir set to {data.get('playlistdir')}")


def current_paths(state):
    paths = []
    for src in state.get("sources", []):
        p = src["mountpoint"] if src.get("type") == "smb" else src.get("path")
        if p and p not in paths:
            paths.append(p)
    return paths


def apply_to_lyrion(state):
    """Write mediadirs into Lyrion prefs and restart + rescan."""
    try:
        import yaml
    except Exception:
        return False, "python3-yaml non installato"

    prefs = _ensure_prefs()
    if not prefs:
        return False, "File prefs di Lyrion non trovato. Verifica che Lyrion sia avviato (systemctl status lyrionmusicserver)."

    paths = current_paths(state)

    # Stop Lyrion so it does not overwrite the prefs file under us.
    _run(["systemctl", "stop", LYRION_SERVICE], timeout=60)
    try:
        with open(prefs) as f:
            data = yaml.safe_load(f) or {}
        data["mediadirs"] = paths
        # keep ignoreInAudioScan in sync (empty list is fine)
        data.setdefault("ignoreInAudioScan", [])
        # ensure a writable playlist folder so "save as playlist" works
        data, _ = _provision_playlistdir(data)
        tmp = prefs + ".tmp"
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, prefs)
        # prefs belong to the squeezeboxserver user
        try:
            import pwd
            uid = pwd.getpwnam("squeezeboxserver").pw_uid
            gid = pwd.getpwnam("squeezeboxserver").pw_gid
            os.chown(prefs, uid, gid)
        except Exception:
            pass
    finally:
        _run(["systemctl", "start", LYRION_SERVICE], timeout=60)

    return True, f"{len(paths)} sorgenti applicate. Lyrion riavviato e in scansione."


# ─────────────────────────── HTTP API ───────────────────────────────
@app.route("/api/sources", methods=["GET"])
def api_list():
    state = load_state()
    out = []
    for s in state.get("sources", []):
        item = dict(s)
        item.pop("password", None)
        if s.get("type") == "smb":
            item["mounted"] = os.path.ismount(s["mountpoint"])
        else:
            item["exists"] = os.path.isdir(s.get("path", ""))
        out.append(item)
    return jsonify({"sources": out, "paths": current_paths(state)})


@app.route("/api/sources/local", methods=["POST"])
def api_add_local():
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "message": "Percorso mancante"}), 400
    # Normalise and confine the path to an allow-listed media root before it is
    # ever touched on disk or stored as a Lyrion media directory.
    path = os.path.realpath(path)
    allowed = False
    for root in ALLOWED_LOCAL_ROOTS:
        root = os.path.realpath(root)
        if path == root or path.startswith(root + os.sep):
            allowed = True
            break
    if not allowed:
        return jsonify({"success": False, "message": "Percorso non consentito"}), 400
    if not os.path.isdir(path):
        return jsonify({"success": False, "message": f"La cartella {path} non esiste"}), 400
    with _lock:
        state = load_state()
        sid = _slug("local", os.path.basename(path.rstrip("/")))
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append({"id": sid, "type": "local", "name": path, "path": path})
        save_state(state)
    return jsonify({"success": True})


@app.route("/api/sources/smb", methods=["POST"])
def api_add_smb():
    data = request.get_json(silent=True) or {}
    server = (data.get("server") or "").strip().strip("/")
    share = (data.get("share") or "").strip().strip("/")
    if not server or not share:
        return jsonify({"success": False, "message": "Server e nome condivisione obbligatori"}), 400
    name = data.get("name") or f"{server}/{share}"
    sid = _slug("smb", server, share)
    src = {
        "id": sid,
        "type": "smb",
        "name": name,
        "server": server,
        "share": share,
        "username": (data.get("username") or "").strip(),
        "password": data.get("password") or "",
        "mountpoint": os.path.join(MOUNT_ROOT, _slug(server, share)),
    }
    ok, msg = mount_smb(src)
    if not ok:
        return jsonify({"success": False, "message": f"Mount fallito: {msg}"}), 400
    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append(src)
        save_state(state)
    return jsonify({"success": True, "message": msg})


@app.route("/api/sources/<sid>", methods=["DELETE"])
def api_remove(sid):
    with _lock:
        state = load_state()
        keep = []
        for s in state["sources"]:
            if s.get("id") == sid:
                if s.get("type") == "smb":
                    umount(s["mountpoint"])
            else:
                keep.append(s)
        state["sources"] = keep
        save_state(state)
    return jsonify({"success": True})


@app.route("/api/apply", methods=["POST"])
def api_apply():
    state = load_state()
    ok, msg = apply_to_lyrion(state)
    return jsonify({"success": ok, "message": msg}), (200 if ok else 500)


# ─────────────────────────── Web UI ─────────────────────────────────
@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Sorgenti musicali</title>
<style>
  :root { --gold:#d4af37; --bg:#0a0a0a; --surface:#161616; --border:#252525; --silver:#c0c0c0; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:#fff; }
  .wrap { max-width:640px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:20px; display:flex; align-items:center; gap:8px; }
  h1 .dot { width:10px; height:10px; border-radius:50%; background:var(--gold); box-shadow:0 0 8px var(--gold); }
  h2 { font-size:14px; color:var(--silver); text-transform:uppercase; letter-spacing:.08em; margin:28px 0 10px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:16px; margin-bottom:12px; }
  label { display:block; font-size:12px; color:var(--silver); margin:8px 0 4px; }
  input { width:100%; background:var(--bg); border:1px solid var(--border); color:#fff; border-radius:10px; padding:11px 12px; font-size:15px; }
  input:focus { outline:none; border-color:var(--gold); }
  button { border:0; border-radius:10px; padding:11px 16px; font-weight:600; font-size:14px; cursor:pointer; }
  .primary { background:var(--gold); color:#000; }
  .ghost { background:rgba(255,255,255,.06); color:#fff; }
  .danger { background:transparent; color:#e66; border:1px solid rgba(238,102,102,.4); }
  .row { display:flex; gap:10px; align-items:center; justify-content:space-between; }
  .src { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:12px 0; border-bottom:1px solid var(--border); }
  .src:last-child { border-bottom:0; }
  .src .meta { min-width:0; }
  .src .name { font-size:14px; word-break:break-all; }
  .src .sub { font-size:12px; color:var(--silver); }
  .tag { font-size:10px; padding:2px 7px; border-radius:6px; background:rgba(212,175,55,.15); color:var(--gold); margin-left:6px; }
  .ok { color:#5fce8f; } .bad { color:#e66; }
  .msg { margin-top:10px; font-size:13px; min-height:18px; }
  .applybar { position:fixed; left:0; right:0; bottom:0; background:#0d0d0dee; backdrop-filter:blur(8px); border-top:1px solid var(--border); padding:12px 16px; }
  .applybar .inner { max-width:640px; margin:0 auto; display:flex; gap:10px; align-items:center; }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot"></span> Sorgenti musicali</h1>
  <p style="color:var(--silver);font-size:14px">Aggiungi le cartelle che contengono la tua musica. Al termine premi <b>Applica</b> per aggiornare la libreria.</p>

  <h2>Sorgenti attive</h2>
  <div class="card" id="list"><div style="color:var(--silver);font-size:14px">Caricamento…</div></div>

  <h2>Aggiungi cartella locale</h2>
  <div class="card">
    <label>Percorso sul dispositivo</label>
    <input id="localPath" placeholder="/media/musica">
    <div style="height:10px"></div>
    <button class="ghost" onclick="addLocal()">Aggiungi cartella locale</button>
    <div class="msg" id="localMsg"></div>
  </div>

  <h2>Aggiungi cartella di rete (SMB)</h2>
  <div class="card">
    <div class="row"><div style="flex:1"><label>Server / IP</label><input id="smbServer" placeholder="192.168.0.20"></div>
    <div style="flex:1"><label>Condivisione</label><input id="smbShare" placeholder="Musica"></div></div>
    <div class="row"><div style="flex:1"><label>Utente (vuoto = ospite)</label><input id="smbUser" placeholder="utente"></div>
    <div style="flex:1"><label>Password</label><input id="smbPass" type="password" placeholder="••••••"></div></div>
    <div style="height:12px"></div>
    <button class="ghost" onclick="addSmb()">Monta e aggiungi</button>
    <div class="msg" id="smbMsg"></div>
  </div>
</div>

<div class="applybar"><div class="inner">
  <button class="primary" style="flex:1" onclick="apply()">Applica e scansiona libreria</button>
  <span class="msg" id="applyMsg" style="margin:0"></span>
</div></div>

<script>
async function j(url, opts){ const r=await fetch(url,opts); return r.json(); }
async function load(){
  const d=await j('/api/sources');
  const el=document.getElementById('list');
  if(!d.sources.length){ el.innerHTML='<div style="color:var(--silver);font-size:14px">Nessuna sorgente. Aggiungine una qui sotto.</div>'; return; }
  el.innerHTML=d.sources.map(s=>{
    const isSmb=s.type==='smb';
    const status=isSmb?(s.mounted?'<span class="ok">montato</span>':'<span class="bad">non montato</span>')
                      :(s.exists?'<span class="ok">ok</span>':'<span class="bad">mancante</span>');
    const sub=isSmb?('//'+s.server+'/'+s.share+' → '+s.mountpoint):s.path;
    return `<div class="src"><div class="meta"><div class="name">${s.name}<span class="tag">${isSmb?'SMB':'LOCALE'}</span></div>
      <div class="sub">${sub} · ${status}</div></div>
      <button class="danger" onclick="rm('${s.id}')">Rimuovi</button></div>`;
  }).join('');
}
async function addLocal(){
  const path=document.getElementById('localPath').value.trim();
  const m=document.getElementById('localMsg'); m.textContent='…';
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  m.textContent=r.success?'Aggiunta ✓':(r.message||'Errore'); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){document.getElementById('localPath').value='';load();}
}
async function addSmb(){
  const body={server:smbServer.value,share:smbShare.value,username:smbUser.value,password:smbPass.value};
  const m=document.getElementById('smbMsg'); m.textContent='Montaggio…';
  const r=await j('/api/sources/smb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  m.textContent=r.success?('Montata ✓ '+(r.message||'')):(r.message||'Errore'); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){smbPass.value='';load();}
}
async function rm(id){ await j('/api/sources/'+id,{method:'DELETE'}); load(); }
async function apply(){
  const m=document.getElementById('applyMsg'); m.textContent='Applico…'; m.className='msg';
  const r=await j('/api/apply',{method:'POST'});
  m.textContent=r.message||(r.success?'Fatto':'Errore'); m.className='msg '+(r.success?'ok':'bad');
}
load();
</script>
</body>
</html>"""

if __name__ == "__main__":
    try:
        os.makedirs(MOUNT_ROOT, exist_ok=True)
    except Exception:
        pass
    # Re-mount known SMB shares on startup (survives reboots)
    try:
        remount_all()
    except Exception as e:
        print(f"[sources] remount_all error: {e}")
    # Make sure Lyrion has a writable playlist folder ("save as playlist")
    try:
        ensure_playlistdir()
    except Exception as e:
        print(f"[sources] ensure_playlistdir error: {e}")
    app.run(host="0.0.0.0", port=8080)
