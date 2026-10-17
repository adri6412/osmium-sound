// Music sources as PLACES — the same model the kiosk draws (SourcesPage.qml):
// this appliance's system disk and second disk(s), the USB sticks, the
// network shares; each with its state, its room and its uses (library,
// shared, playlists, CD rip). Only what is connected and mounted is a place.
import { api } from './api.js';

export function under(p, r) {
  p = String(p || ''); r = String(r || '');
  return !!r && (p === r || p.startsWith(r + '/'));
}

export function gb(n) {
  const v = Number(n) || 0;
  if (v >= 1024 ** 4) return `${(v / 1024 ** 4).toFixed(1)} TB`;
  if (v >= 10 * 1024 ** 3) return `${Math.round(v / 1024 ** 3)} GB`;
  if (v >= 1024 ** 3) return `${(v / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(v / 1024 ** 2)} MB`;
}

// Disks music can go on: not the eMMC boot areas, the RAM swap or anything tiny.
function realDisk(k) {
  const p = String(k.path || '');
  return !(p.includes('boot0') || p.includes('boot1') || p.startsWith('/dev/zram') || p.startsWith('/dev/loop')
           || String(k.fstype || '') === 'swap' || Number(k.size || 0) < 1e9);
}

export async function loadSources() {
  const [s, usb, disks, smb, pl, cd, roots, fmt] = await Promise.all([
    api.sourcesList(), api.usbList(), api.internalDisks(), api.internalSmb(), api.playlistdirGet(),
    api.cdSettings(), api.filesList(''), api.internalFormatStatus(),
  ]);
  const d = (r) => (r && r.ok && r.data && typeof r.data === 'object' ? r.data : {});
  const out = {
    srcs: d(s).sources || [],
    libPaths: (d(s).paths || []).map(String),
    usbBad: d(usb).disks || [],
    disks: (d(disks).disks || []).filter(realDisk).map((k) => ({
      path: String(k.path || ''), model: String(k.model || ''), confirm: String(k.confirm || ''), size: Number(k.size || 0),
      adopted: !!k.adopted, hasData: !!k.has_data,
      parts: (k.partitions || []).filter((p) => p.fstype).map((p) => ({ path: String(p.path || ''), fs: String(p.fstype), label: String(p.label || '') })),
    })),
    smb: d(smb),
    shares: (d(smb).shares || []).map((x) => (typeof x === 'string' ? { name: x, mountpoint: '' } : { name: String(x.name || ''), mountpoint: String(x.mountpoint || '') })),
    pldir: String(d(pl).path || ''),
    cd: d(cd).settings || {},
    roots: d(roots).entries || [],
    fmt: d(fmt),
    loaded: true,
  };
  for (const e of ['albums', 'songs']) {
    const r = await api.lyrionQuery(['info', 'total', e, '?']);
    out[e] = r.ok && r.data && r.data['_' + e] !== undefined ? Number(r.data['_' + e]) : null;
  }
  out.places = buildPlaces(out);
  return out;
}

// `lt(it, en)` is filled in by the caller (it knows the language).
let lt = (it) => it;
export function setLang(fn) { lt = fn; }

export function buildPlaces(m) {
  const out = [];
  const music = m.roots.find((r) => String(r.kind) === 'music');
  const mk = (key, group, glyph, name, kind, root) => ({
    key, group, glyph, name, kind, root, ok: true, rw: true, usage: null, src: null,
    locals: [], lib: false, shared: false, playlist: false, rip: false, error: '', removable: false,
  });
  const sys = mk('sys', 'dev', 'hard-drive', lt('Disco di sistema', 'System disk'), lt('Qui è installato Osmium', 'Osmium is installed here'), music ? String(music.path) : '');
  sys.usage = music ? music.usage || null : null;
  out.push(sys);
  const internals = m.srcs.filter((s) => s.type === 'internal');
  internals.forEach((s) => {
    const name = internals.length === 1 ? lt('Secondo disco', 'Second disk') : `${lt('Disco', 'Disk')} «${s.label || s.name}»`;
    const p = mk(String(s.id), 'dev', 'hard-drive', name, (s.model ? s.model + ' · ' : '') + lt("montato dentro l'apparecchio", 'mounted inside the appliance'), String(s.mountpoint || ''));
    Object.assign(p, { src: s, ok: !!s.mounted, usage: s.usage || null, removable: true });
    if (!p.ok) p.error = lt('Non montato', 'Not mounted');
    out.push(p);
  });
  m.srcs.filter((s) => s.type === 'usb' && s.mounted).forEach((u) => {
    const p = mk(String(u.id), 'usb', 'usb', String(u.label || u.name || 'USB'), lt('Chiavetta o disco USB', 'USB stick or disk'), String(u.mountpoint || ''));
    Object.assign(p, { src: u, usage: u.usage || null, removable: true });
    out.push(p);
  });
  m.srcs.filter((s) => s.type === 'smb').forEach((n) => {
    const p = mk(String(n.id), 'net', 'network', `${n.server} › ${n.share}`, `${lt('Cartella di rete', 'Network folder')} · //${n.server}/${n.share}`, String(n.mountpoint || ''));
    Object.assign(p, { src: n, ok: !!n.mounted, usage: n.usage || null, rw: !!n.rw, removable: true });
    if (!p.ok) p.error = n.mount_error && n.mount_error.message ? String(n.mount_error.message) : lt('Non risponde: è acceso e sulla stessa rete?', 'Not answering: is it on, and on the same network?');
    out.push(p);
  });
  m.srcs.filter((s) => s.type === 'local').forEach((l) => {
    let host = sys;
    for (let k = 1; k < out.length; k++) if (under(l.path, out[k].root)) host = out[k];
    host.locals.push(l);
  });
  for (const q of out) {
    q.lib = q.locals.length > 0 || m.libPaths.some((x) => under(x, q.root));
    q.shared = m.shares.some((x) => under(x.mountpoint, q.root)) || q.locals.some((x) => !!x.samba);
  }
  const owner = (path) => { if (!path) return sys; for (let j = out.length - 1; j >= 1; j--) if (under(path, out[j].root)) return out[j]; return sys; };
  owner(m.pldir).playlist = true;
  owner(String((m.cd && m.cd.target) || '')).rip = true;
  return out;
}

export function placeFor(places, path) {
  let best = null;
  for (const p of places || []) if (p.root && under(path, p.root) && (!best || p.root.length > best.root.length)) best = p;
  return best;
}

export function glyphOf(e) {
  if (e.dir) return 'folder';
  const n = String(e.name).toLowerCase();
  if (/\.(flac|mp3|wav|m4a|aac|ogg|opus|aiff?|dsf|dff|ape|wv|mpc|wma)$/.test(n)) return 'music';
  if (/\.(jpe?g|png|webp|gif|bmp|tiff?)$/.test(n)) return 'image';
  if (/\.(m3u8?|pls|xspf|cue)$/.test(n)) return 'list-music';
  return 'file';
}

export function fmtSize(e) {
  if (e.dir) return '';
  const n = Number(e.size) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}
