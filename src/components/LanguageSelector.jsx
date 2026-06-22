import React from 'react';
import { Check } from 'lucide-react';
import { useI18n } from '../i18n';

/**
 * Language picker shared by the setup wizard and the Settings screen.
 *
 * variant="compact" → small inline pill buttons (used in the wizard top bar)
 * variant="list"    → full-width selectable rows (used in Settings)
 */
const LanguageSelector = ({ variant = 'list' }) => {
  const { lang, setLang, languages } = useI18n();

  if (variant === 'compact') {
    return (
      <div className="flex items-center space-x-1">
        {languages.map((l) => {
          const active = l.code === lang;
          return (
            <button
              key={l.code}
              onClick={() => setLang(l.code)}
              className={`px-2 py-1 rounded-md text-[11px] font-semibold uppercase tracking-wide transition-colors ${
                active
                  ? 'bg-hifi-gold/20 text-hifi-gold'
                  : 'text-hifi-silver/50 hover:text-hifi-silver hover:bg-white/5'
              }`}
              title={l.name}
            >
              <span className="mr-1">{l.flag}</span>{l.code.toUpperCase()}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {languages.map((l) => {
        const active = l.code === lang;
        return (
          <button
            key={l.code}
            onClick={() => setLang(l.code)}
            className={`w-full flex items-center justify-between p-3 rounded-lg text-left transition-colors ${
              active ? 'bg-hifi-gold text-black' : 'bg-hifi-light text-white hover:bg-hifi-accent'
            }`}
          >
            <span className="flex items-center space-x-3">
              <span className="text-xl">{l.flag}</span>
              <span className="font-medium text-sm">{l.name}</span>
            </span>
            {active && <Check size={18} />}
          </button>
        );
      })}
    </div>
  );
};

export default LanguageSelector;
