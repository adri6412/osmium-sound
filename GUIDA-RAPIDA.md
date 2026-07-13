# 🎵 Osmium Sound — Guida Rapida

*[Read in English](QUICKSTART.md)*

Come installare e iniziare a usare Osmium Sound sul tuo mini-PC x86.

## 🚀 Installazione

1. **Scarica la ISO** dell'ultima release da
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases).
2. **Scrivi la ISO** su una chiavetta USB da 8&nbsp;GB o più, con
   [balenaEtcher](https://etcher.balena.io/), Rufus o `dd`.
3. **Avvia il mini-PC dalla chiavetta** e segui l'installazione guidata a schermo.
   Al riavvio, l'appliance è pronta.

> ⚠️ **Installazione non presidiata — formatta un disco automaticamente.**
> La ISO non fa domande e non chiede conferme: sceglie il **primo disco che
> rileva**, lo cancella del tutto (nuovo GPT, tutte le partizioni e i dati
> persi) e si riavvia da sola. Usala solo su una macchina senza dati da
> conservare, e scollega prima ogni disco che non vuoi toccare.

**Nota:** la ISO serve solo per la prima installazione. Tutti gli aggiornamenti
successivi (interfaccia, sistema, OS, Lyrion) arrivano automaticamente via
**OTA** dalla schermata Impostazioni — non serve riflashare nulla.

## 🧙 Primo avvio

Al primo avvio parte la **procedura guidata di configurazione**: rete,
libreria musicale, DAC/uscita audio e (se manca) l'installazione automatica
di Lyrion Music Server. Da lì in poi l'app si apre direttamente sulla
schermata principale.

## 🎮 Come si usa

- **Musica / Radio / App**: interfaccia per Lyrion Music Server — libreria
  locale, radio internet e servizi di streaming (Deezer, Qobuz, TIDAL,
  Spotify e altri) tramite i **plugin di Lyrion**. Installa il plugin che ti
  serve dalla web UI di Lyrion (Impostazioni → Plugin): compare da solo nei
  tab Radio/App, senza bisogno di aggiornare l'app.
- **Impostazioni**: info di sistema e rete, scelta del DAC/uscita audio, DSP
  opzionale (EQ, crossfeed, correzione ambientale), Multiroom, aggiornamenti
  OTA (canale Dev/Prod), abbinamento dell'app companion Android.

## 📱 App companion Android

Controlla Osmium Sound dal telefono — sfoglia la libreria, gestisci
riproduzione e coda, regola il volume. Abbina scansionando il QR code da
Impostazioni sul dispositivo. Distribuita come APK firmato o tramite il
nostro repo F-Droid self-hosted — non è sul Play Store. Dettagli su
[osmiumsound.qd.je](https://osmiumsound.qd.je/#android).

## 🔧 Problemi comuni

- **Il front-end Lyrion non carica**: verifica l'URL del server Lyrion nelle
  Impostazioni (default `http://localhost:9000`) e che il servizio sia attivo.
- **Sorgenti streaming/radio mancanti**: installa il plugin corrispondente
  dalla web UI di Lyrion.
- **Audio non funziona**: controlla il dispositivo audio selezionato in
  Impostazioni e che il DAC sia riconosciuto.

## 📚 Altre risorse

- **[README.md](README.md)**: panoramica, funzioni e specifiche
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: dettagli tecnici, API, sviluppo locale
- Note di rilascio: [changelog sul sito](https://osmiumsound.qd.je/#changelog)

---

**Buon ascolto con Osmium Sound! 🎶**
