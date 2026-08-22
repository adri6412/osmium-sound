# Translations / Traduzioni (kiosk UI)

Each language of the on-screen Electron kiosk is a single JSON file in this
folder, named with its language code:

- `en.json` → English (the **default** and the fallback for missing keys)
- `it.json` → Italiano

The other two front-ends have their own, separate string sets — they are hand
maintained and do **not** share keys with this folder:

- web admin: `admin-webui/src/i18n/locales/{en,it}.json`
- Android companion: `android-companion/HiFiMediaPlayer/src/main/res/values*/strings.xml`
- backend messages (API errors/status shown to the user): `hifi_i18n.py`,
  selected per request by the `X-UI-Lang` header.

Everything user-visible must exist in **both** English and Italian (the only
deliberate exception is the live-USB installer page, which is English-only).

## Add a new language (no programming needed)

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
5. Save the file. The new language appears automatically in Settings →
   Language (and in the setup wizard's language step, which reads the same
   list). No rebuild step beyond the normal app build.

## Tips

- The file must stay valid JSON. If the app shows the key name instead of the
  text (e.g. `wizard.welcome.title`), there is likely a typo or a missing
  comma/quote in your file — paste it into a JSON validator to find the issue.
- Anything you leave out (or that is added in a future version) falls back to
  **English**, so a partial translation still works.
