import { ref } from 'vue';

// Lightweight i18n, mirroring the Electron kiosk's approach (src/i18n) so the
// two frontends share the same conventions without sharing code: every
// language lives in its own JSON file under ./locales (with a `_meta` block:
// { name, flag, locale }), auto-loaded by Vite. Adding a language is just
// dropping in a new <code>.json file — no code changes.
//
// Unlike the kiosk's React context, this is a module-level singleton: `lang`
// is a single shared ref, so every component that calls useI18n() re-renders
// together when the language changes — the Vue-idiomatic equivalent of a
// global store for a single cross-cutting concern like this.

const modules = import.meta.glob('./locales/*.json', { eager: true });

const locales = {};
for (const path in modules) {
  const code = path.match(/\/([A-Za-z-]+)\.json$/)?.[1];
  if (code) locales[code] = modules[path].default || modules[path];
}

export const DEFAULT_LANG = 'it';
const STORAGE_KEY = 'webuiLanguage';

export const availableLanguages = Object.keys(locales)
  .map((code) => ({
    code,
    name: locales[code]?._meta?.name || code.toUpperCase(),
    flag: locales[code]?._meta?.flag || '',
  }))
  .sort((a, b) => a.name.localeCompare(b.name));

function detectDefault() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && locales[saved]) return saved;
  } catch (_) { /* localStorage unavailable (rare, private mode edge cases) */ }
  const nav = (navigator.language || '').slice(0, 2).toLowerCase();
  if (locales[nav]) return nav;
  return locales[DEFAULT_LANG] ? DEFAULT_LANG : (Object.keys(locales)[0] || DEFAULT_LANG);
}

const lang = ref(detectDefault());

function setLang(l) {
  if (!locales[l]) return;
  try { localStorage.setItem(STORAGE_KEY, l); } catch (_) {}
  lang.value = l;
}

function getNested(obj, key) {
  return key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

// Translate a dotted key, with optional {placeholder} interpolation. Falls
// back to the default language, then to the key itself. Reads lang.value, so
// calling this from a template tracks it as a reactive dependency.
function t(key, vars) {
  let str = getNested(locales[lang.value], key);
  if (str == null) str = getNested(locales[DEFAULT_LANG], key);
  if (str == null) return key;
  if (vars) {
    for (const k in vars) str = str.split(`{${k}}`).join(String(vars[k]));
  }
  return str;
}

export function useI18n() {
  return { lang, setLang, t, languages: availableLanguages };
}
