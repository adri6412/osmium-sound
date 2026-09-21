// Shared vocabulary of the Library editor: the tag keys it may change, the
// credit roles and their groups (as hifi_metadata.py sorts them), the labels
// the kiosk shows for roles and instruments (library.meta.* in the locale
// files is a copy of the kiosk's meta.* strings), dates and track lists as
// text. Ported from native-ui-qt/qml/Meta.qml so the two read the same.
import { useI18n } from '../i18n';
import enStrings from '../i18n/locales/en.json';

const { t, lang } = useI18n();

// ── tags ─────────────────────────────────────────────────────────────
// The keys the device may write (hifi_tags.py whitelist), in the order the
// "all tags" editor lists them. Anything else in a file is shown read-only.
export const EDITABLE_KEYS = [
  'TITLE', 'ARTIST', 'ALBUMARTIST', 'ALBUM', 'TRACKNUMBER', 'TRACKTOTAL', 'DISCNUMBER', 'DISCTOTAL',
  'DATE', 'ORIGINALDATE', 'GENRE', 'COMPOSER', 'CONDUCTOR', 'LYRICIST', 'ARRANGER', 'BAND', 'PERFORMER',
  'PRODUCER', 'ENGINEER', 'MIXER', 'REMIXER', 'LABEL', 'CATALOGNUMBER', 'COMMENT', 'COMPILATION',
  'RELEASETYPE', 'ISRC', 'MUSICBRAINZ_ALBUMID', 'MUSICBRAINZ_ALBUMARTISTID', 'MUSICBRAINZ_ARTISTID',
  'MUSICBRAINZ_TRACKID', 'MUSICBRAINZ_RELEASEGROUPID', 'MUSICBRAINZ_RELEASETRACKID',
];
export const EDITABLE = new Set(EDITABLE_KEYS);
// Keys that commonly hold one value: a single field instead of a list.
export const SINGLE_KEYS = new Set([
  'TITLE', 'ALBUM', 'TRACKNUMBER', 'TRACKTOTAL', 'DISCNUMBER', 'DISCTOTAL', 'DATE', 'ORIGINALDATE',
  'COMPILATION', 'RELEASETYPE', 'COMMENT', 'MUSICBRAINZ_ALBUMID', 'MUSICBRAINZ_ALBUMARTISTID',
  'MUSICBRAINZ_TRACKID', 'MUSICBRAINZ_RELEASEGROUPID', 'MUSICBRAINZ_RELEASETRACKID', 'CATALOGNUMBER',
]);
export const NUMERIC_KEYS = new Set(['TRACKNUMBER', 'TRACKTOTAL', 'DISCNUMBER', 'DISCTOTAL']);
export function tagLabel(key) {
  const s = t('library.tag.' + key);
  return s === 'library.tag.' + key ? key : s;
}

// ── credits ──────────────────────────────────────────────────────────
export const GROUP_ORDER = ['performer', 'composition', 'production', 'engineering', 'other'];
export const ROLE_GROUPS = {
  performer: ['instrument', 'vocal', 'performer', 'performing_orchestra', 'conductor', 'chorus_master', 'concertmaster'],
  composition: ['composer', 'lyricist', 'librettist', 'writer', 'arranger', 'orchestrator', 'translator'],
  production: ['producer', 'liner_notes', 'design', 'photography', 'illustration', 'art_direction', 'graphic_design'],
  engineering: ['engineer', 'recording', 'mix', 'mastering', 'sound', 'audio', 'programming', 'balance', 'editor', 'remixer'],
  other: ['band', 'artist'],
};
// Roles whose `attr` names an instrument or a voice (one line per instrument).
export const PER_ATTR_ROLES = ['instrument', 'vocal', 'arranger', 'orchestrator'];
const VOCAL_WORDS = /vocals$/;

function tt(key, fallback) {
  const s = t(key);
  return s === key ? fallback : s;
}
export function humanize(s) {
  s = String(s || '').replace(/_/g, ' ');
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}
// MusicBrainz sends instruments in lower case ("hammond organ"); a few of the
// kiosk's labels are keyed with capitals ("Hammond organ").
const INSTRUMENT_CASE = {};
export function instrumentLabel(attr) {
  const exact = tt('library.meta.instrument.' + attr, null);
  if (exact !== null) return exact;
  const key = INSTRUMENT_CASE[String(attr).toLowerCase()];
  return key ? tt('library.meta.instrument.' + key, humanize(attr)) : humanize(attr);
}
export function roleName(role) {
  return tt('library.meta.role.' + role, humanize(role));
}
// What a credit line says: "Tenor saxophone", "Producer", "Sound engineer
// (assistant)"... — Meta.qml's roleLabel.
export function roleLabel(e) {
  if (!e) return '';
  const role = String(e.role || ''), attr = String(e.attr || '');
  if ((role === 'instrument' || role === 'vocal') && e.credit) {
    const c = String(e.credit);
    return c.charAt(0).toUpperCase() + c.slice(1);
  }
  if ((role === 'instrument' || role === 'vocal') && attr) return instrumentLabel(attr);
  if (role === 'producer' && attr === 'executive') return tt('library.meta.role.executive', 'Executive producer');
  const base = roleName(role);
  if (!attr || role === 'instrument' || role === 'vocal') return base;
  const words = attr.split(' ').map((w) => tt('library.meta.attr.' + w, tt('library.meta.instrument.' + w, w)).toLowerCase());
  return base + ' (' + words.join(', ') + ')';
}
export function groupLabel(g) {
  return tt('library.meta.group.' + g, humanize(g));
}
// MusicBrainz's artist types: person, group, orchestra, choir…
export function artistTypeName(type) {
  return type ? tt('library.artist.type.' + String(type).toLowerCase(), humanize(type)) : '';
}
export function groupOfRole(role) {
  for (const g of GROUP_ORDER) if (ROLE_GROUPS[g].includes(role)) return g;
  return 'other';
}
// Suggestions for the instrument / voice / qualifier field of a credit line.
// (the keys are MusicBrainz's English names, the same in every locale file)
const INSTRUMENTS = Object.keys((enStrings.library && enStrings.library.meta && enStrings.library.meta.instrument) || {});
for (const k of INSTRUMENTS) INSTRUMENT_CASE[k.toLowerCase()] = k;
export function attrSuggestions(role) {
  const instruments = INSTRUMENTS;
  if (role === 'vocal') return instruments.filter((k) => VOCAL_WORDS.test(k));
  if (role === 'instrument' || role === 'arranger' || role === 'orchestrator') return instruments.filter((k) => !VOCAL_WORDS.test(k));
  return ['assistant', 'additional', 'associate', 'co', 'executive', 'guest', 'solo'];
}
export function attrSuggestionLabel(role, key) {
  if (role === 'vocal' || role === 'instrument' || role === 'arranger' || role === 'orchestrator') return instrumentLabel(key);
  return tt('library.meta.attr.' + key, key);
}

// The comparison form of a name, as hifi_metadata.normalise() computes it —
// only used when a reply comes without the person's `key`.
export function normalise(text) {
  let s = String(text || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/&/g, ' and ');
  s = s.replace(/[\u2018\u2019`\u00b4']/g, '');
  s = s.replace(/[^0-9a-z\u0080-\uffff]+/g, ' ').trim();
  s = s.replace(/^(.*) the$/, 'the $1').replace(/^the /, '');
  return s.replace(/\s+/g, ' ');
}
export function creditKey(e) {
  return e.key || [e.group || '', e.role || '', e.attr || '', e.credit || ''].join('|');
}
export function personKey(p) {
  return p.key || (p.mbid ? String(p.mbid) : 'name:' + normalise(p.name));
}

// ── text ─────────────────────────────────────────────────────────────
export function locale() {
  return lang.value === 'it' ? 'it-IT' : 'en-GB';
}
// "1959", "1959-08" or "1959-08-17" as the page's language writes them
export function fmtDate(d) {
  d = String(d || '');
  const m = d.match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/);
  if (!m) return d;
  if (!m[2]) return m[1];
  const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3] || 1));
  return dt.toLocaleDateString(locale(), m[3] ? { day: 'numeric', month: 'long', year: 'numeric' } : { month: 'long', year: 'numeric' });
}
export function fmtWhen(ts) {
  return new Date(Number(ts) * 1000).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' });
}
// [[1,1],[1,2],[1,3],[1,5]] -> "1–3, 5"; on several discs "1.1–1.3, 2.4"
export function trackList(tracks, discs) {
  if (!tracks || !tracks.length) return '';
  const tr = tracks.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = [];
  const name = (x) => (discs > 1 ? x[0] + '.' + x[1] : String(x[1]));
  let i = 0;
  while (i < tr.length) {
    let j = i;
    while (j + 1 < tr.length && tr[j + 1][0] === tr[i][0] && tr[j + 1][1] === tr[j][1] + 1) j++;
    out.push(j > i + 1 ? name(tr[i]) + '–' + name(tr[j]) : j === i + 1 ? name(tr[i]) + ', ' + name(tr[j]) : name(tr[i]));
    i = j + 1;
  }
  return out.join(', ');
}
export function fmtDuration(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
}
export const clone = (x) => JSON.parse(JSON.stringify(x));
