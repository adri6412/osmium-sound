# Piano di Rebranding per Osmium Sound Companion

## 1. Modifiche all'Application ID
- **File**: `android-companion/HiFiMediaPlayer/build.gradle`
- **Modifica**: Cambiare `namespace 'com.hifi.mediaplayer'` in `namespace 'com.osmium.sound.companion'`

## 2. Modifiche al Nome dell'App
- **File**: `android-companion/HiFiMediaPlayer/src/main/res/values/strings.xml`
- **Modifica**: La stringa `app_name` è già impostata su "Osmium Sound Companion", quindi non è necessario modificarla.

## 3. Modifiche alle Risorse Grafiche (Logo)
- **File**: Tutti i file in `android-companion/HiFiMediaPlayer/src/main/res/mipmap-*`
- **Modifica**: Sostituire tutti i file `ic_launcher*.png` e `ic_launcher*.xml` con le nuove risorse del brand Osmium Sound.

## 4. Verifica della Licenza
- **Stato**: La licenza Apache 2.0 è già presente nei file:
  - `android-companion/HiFiMediaPlayer/src/main/AndroidManifest.xml` (righe 3-17)
  - `android-companion/HiFiMediaPlayer/src/main/res/values/strings.xml` (righe 1-15)
- **Informazioni di Copyright**: Presenti in `android-companion/HiFiMediaPlayer/src/main/res/values/strings.xml` (righe 221-223)

## 5. Ulteriori Considerazioni
- Creare un logo originale per l'app.
- Aggiornare i colori dell'interfaccia utente per allinearsi al branding di Osmium Sound.
- Verificare che tutte le stringhe di testo siano appropriate per il nuovo brand.
- Aggiornare eventuali riferimenti a "Squeezer" nel codice o nella documentazione.