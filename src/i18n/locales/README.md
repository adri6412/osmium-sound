# Translations / Traduzioni (on-screen UI)

Each language of the on-screen interface is a single JSON file in this folder,
named with its language code:

- `en.json` → English (the **default** and the fallback for missing keys)
- `it.json` → Italiano

The on-screen interface is the Qt one (`native-ui-qt/`):
`native-ui-qt/ci/build-payload.sh` copies `en.json` and `it.json` into
`/opt/hifi-qt/locales`, and `native-ui-qt/src/i18n.cpp` loads them at runtime.
The legacy Electron kiosk (`src/i18n/index.jsx`) reads the very same files.

The other two front-ends have their own, separate string sets — they are hand
maintained and do **not** share keys with this folder:

- web admin: `admin-webui/src/i18n/locales/{en,it}.json`
- Android companion: `android-companion/HiFiMediaPlayer/src/main/res/values*/strings.xml`
- backend messages (API errors/status shown to the user): `hifi_i18n.py`,
  selected per request by the `X-UI-Lang` header.

Everything user-visible must exist in **both** English and Italian (the only
deliberate exception is the live-USB installer page, which is English-only).

## Add a new language (no programming needed for the translation itself)

1. Copy `en.json` and rename the copy to your language code, e.g. `fr.json`
   (French), `de.json` (German), `es.json` (Spanish).
2. Open the new file and edit the `_meta` block at the top:
   ```json
   "_meta": {
     "name": "Français",     // language name as shown in the menu
     "flag": "🇫🇷",          // optional flag emoji
     "locale": "fr-FR"       // used for the clock/date format
   }
   ```
3. Translate **only the text on the right side** of each `:` — for example
   change `"back": "Back"` to `"back": "Retour"`. **Do not** change the words on
   the left (the "keys"), and keep all the quotes, commas and braces exactly as
   they are.
4. Leave anything inside curly braces untouched, e.g. `{ip}`, `{ssid}`,
   `{version}`. Those are filled in automatically by the app.
5. Save the file. The legacy Electron kiosk lists it in Settings → Language on
   its own (from `_meta`). The Qt interface does not yet: a developer has to
   add the file to the copy in `native-ui-qt/ci/build-payload.sh` and the
   language to the list in `native-ui-qt/qml/SettingsTab.qml`
   (`secLanguage()`), then rebuild the payload.

## Tips

- The file must stay valid JSON. If the Qt interface stays in English after
  you pick the language, the file is probably not valid (`journalctl -u hifi-qt`
  shows an `i18n:` warning naming it) — paste it into a JSON validator to find
  the typo or the missing comma/quote. A key name shown instead of the text
  (e.g. `wizard.welcome.title`) means that key is missing from `en.json` too.
- Anything you leave out (or that is added in a future version) falls back to
  **English**, so a partial translation still works.
