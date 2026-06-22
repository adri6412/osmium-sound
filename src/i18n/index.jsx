import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Lightweight i18n (no external dependency).
//
// Every language lives in its own JSON file under ./locales (e.g. it.json,
// en.json). Anyone can add a new language by copying one of those files,
// translating the values, and saving it as <code>.json (for example fr.json).
// Vite picks it up automatically — no code changes required.
//
// Each locale file should start with a `_meta` block describing the language:
//   { "_meta": { "name": "Français", "flag": "🇫🇷" }, ... }
// ─────────────────────────────────────────────────────────────────────────────

// Auto-load every locale file in ./locales.
const modules = import.meta.glob('./locales/*.json', { eager: true });

const locales = {};
for (const path in modules) {
  const code = path.match(/\/([A-Za-z-]+)\.json$/)?.[1];
  if (code) locales[code] = modules[path].default || modules[path];
}

export const DEFAULT_LANG = 'it';

// List of selectable languages, derived from the loaded files.
export const availableLanguages = Object.keys(locales)
  .map((code) => ({
    code,
    name: locales[code]?._meta?.name || code.toUpperCase(),
    flag: locales[code]?._meta?.flag || '',
  }))
  .sort((a, b) => a.name.localeCompare(b.name));

// Maps a language code to a BCP-47 locale for date/number formatting.
export const localeTag = (lang) =>
  (locales[lang]?._meta?.locale) || (lang === 'it' ? 'it-IT' : 'en-US');

const getNested = (obj, key) =>
  key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);

const I18nContext = createContext(null);

export const I18nProvider = ({ children }) => {
  const [lang, setLangState] = useState(() => {
    const saved = localStorage.getItem('appLanguage');
    if (saved && locales[saved]) return saved;
    return locales[DEFAULT_LANG] ? DEFAULT_LANG : (Object.keys(locales)[0] || DEFAULT_LANG);
  });

  const setLang = useCallback((l) => {
    if (!locales[l]) return;
    localStorage.setItem('appLanguage', l);
    setLangState(l);
  }, []);

  // Translate a dotted key, with optional {placeholder} interpolation.
  // Falls back to the default language, then to the key itself.
  const t = useCallback((key, vars) => {
    let str = getNested(locales[lang], key);
    if (str == null) str = getNested(locales[DEFAULT_LANG], key);
    if (str == null) return key;
    if (vars) {
      for (const k in vars) str = str.split(`{${k}}`).join(String(vars[k]));
    }
    return str;
  }, [lang]);

  const value = useMemo(
    () => ({ lang, setLang, t, languages: availableLanguages, localeTag: () => localeTag(lang) }),
    [lang, setLang, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = () => {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within an I18nProvider');
  return ctx;
};
