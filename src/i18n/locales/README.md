# Translations / Traduzioni

Each language is a single JSON file in this folder, named with its language code:

- `it.json` → Italiano
- `en.json` → English

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
5. Save the file. The new language appears automatically in the setup wizard and
   in Settings → Language. No rebuild step beyond the normal app build.

## Tips

- The file must stay valid JSON. If the app shows the key name instead of the
  text (e.g. `wizard.welcome.title`), there is likely a typo or a missing
  comma/quote in your file — paste it into a JSON validator to find the issue.
- Anything you leave out (or that is added in a future version) falls back to
  Italian, so a partial translation still works.
