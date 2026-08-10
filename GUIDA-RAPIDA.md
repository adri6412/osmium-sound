# 🎵 Osmium Sound — Guida Rapida

*[Read in English](QUICKSTART.md)*

Come installare e iniziare a usare Osmium Sound sul tuo mini-PC x86.

## 🚀 Installazione

1. **Scarica la ISO** dell'ultima release da
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases).
2. **Scrivi la ISO** su una chiavetta USB da 8&nbsp;GB o più, con
   [balenaEtcher](https://etcher.balena.io/), Rufus o `dd`.
3. **Avvia il mini-PC dalla chiavetta.** Lo schermo mostra solo un QR code —
   non serve mai mouse o tastiera. Scansionalo con il telefono: il resto
   dell'installazione (scelta del disco, conferma, avvio) avviene dal
   telefono. Lo schermo mostra l'avanzamento in sola lettura e si riavvia da
   solo al termine.

> **Selezione del disco.** Scegli dal telefono su quale disco installare;
> viene cancellato solo quello — nulla viene cancellato senza conferma.
> Testato finora solo su UEFI (avvio BIOS/legacy non ancora verificato con
> questo flusso).

> **Provala in modalità live.** Scegli **Try Osmium Sound (no install)** nel
> menu di avvio per far partire il kiosk direttamente dalla chiavetta USB —
> senza scrivere nulla sul disco. Se non fa l'accesso automatico, usa
> `hifi` / `hifi` alla schermata di login.

**Nota:** la ISO serve solo per la prima installazione. Tutti gli aggiornamenti
successivi (interfaccia, sistema, OS, Lyrion) arrivano automaticamente via
**OTA** dalla schermata Impostazioni — non serve riflashare nulla.

## 🧙 Primo avvio

Al primo avvio dopo l'installazione, lo schermo mostra di nuovo solo un QR
code. Scansionalo con il telefono per completare la **configurazione
guidata**, interamente dal telefono: lingua, ripristino da un backup
precedente oppure configurazione da zero, connessione alla rete, modalità
del dispositivo (con schermo, headless o solo server — vedi sotto), uscita
audio, Lyrion Music Server (locale o un server già presente in rete),
sorgenti musicali e fuso orario. Una volta terminato dal telefono, il
dispositivo prosegue da solo — nessun pulsante da premere sullo schermo. Da
lì in poi l'app si apre direttamente sulla schermata principale (oppure
resta headless, a seconda di cosa hai scelto).

> **Se ti connetti via Wi-Fi**, l'hotspot di configurazione si spegne non
> appena il dispositivo si collega alla tua rete di casa (una singola scheda
> Wi-Fi non può fare entrambe le cose insieme) — riconnetti il telefono alla
> tua rete Wi-Fi e apri `https://hifiplayer.local` per riprendere il resto
> della configurazione. Con il cavo Ethernet non c'è questa interruzione:
> l'hotspot resta acceso per tutto il tempo.

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

## 🖥️ Modalità dispositivo, headless e amministrazione web

Osmium Sound può funzionare **con schermo** (kiosk touchscreen), **headless**
(senza schermo, gestito da browser o dall'app companion) oppure **solo
server** (senza schermo *e* senza riproduzione audio in locale — per un
dispositivo il cui unico compito è servire Lyrion Music Server ad altri
player Osmium in casa).

**Primo avvio (installazione nuova o dopo un reset di fabbrica):**
1. Il dispositivo alza un hotspot Wi-Fi **`Osmium-Setup-XXXX`** (WPA2,
   passphrase `osmiumsetup`). Collega il telefono — la pagina di
   configurazione si apre da sola (captive portal). Se non succede, apri
   **http://10.42.0.1**.
2. Segui la pagina di configurazione dal telefono: lingua, ripristino da
   backup oppure configurazione da zero, Wi-Fi di casa (o cavo), modalità
   del dispositivo (**con schermo** / **headless** / **solo server**),
   uscita audio, Lyrion (locale o un server già presente in rete), sorgenti
   musicali e fuso orario.
3. Premi *Completa setup*. L'hotspot di configurazione si spegne;
   riconnetti il telefono alla tua rete e apri **https://hifiplayer.local**
   per creare l'account di amministrazione web (utente + password). Il
   browser avviserà che il certificato "non è affidabile" — è normale su un
   dispositivo locale (non esiste un'autorità di certificazione pubblica);
   la connessione resta comunque cifrata. Accetta e prosegui.

**Ripristinare invece di configurare da zero:** nella stessa pagina di
configurazione, carica un file di backup precedente (e la relativa
passphrase, se cifrato) invece di seguire i vari passaggi — rete, audio,
Lyrion, sorgenti e fuso orario vengono tutti ripristinati da lì, e il
dispositivo si riavvia per applicarli.

**Gestire un dispositivo headless o solo server:** apri
**https://hifiplayer.local** (amministrazione web — rete, audio,
aggiornamenti, modalità schermo, player on/off, account, reset di fabbrica),
l'**app companion**, oppure la libreria Lyrion su
**http://hifiplayer.local:9000**.

**Cambiare modalità in seguito:** Impostazioni → *Modalità schermo*
(con schermo ⇄ headless) e Impostazioni → *Player* (acceso ⇄ spento, per
solo server) — a schermo se ne hai uno, oppure dall'amministrazione
web/app companion se non ne hai. È questo il modo per riaccendere lo
schermo su un'unità headless.

**Reset di fabbrica:** Impostazioni → *Reset di fabbrica* (a schermo),
oppure dall'amministrazione web (con la password). Cancella tutte le
impostazioni **e l'account di amministrazione web**, poi riavvia tornando
a questo stesso flusso di configurazione via QR code.

## 📚 Altre risorse

- **[README.md](README.md)**: panoramica, funzioni e specifiche
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: dettagli tecnici, API, sviluppo locale
- Note di rilascio: [changelog sul sito](https://osmiumsound.qd.je/#changelog)

---

**Buon ascolto con Osmium Sound! 🎶**
