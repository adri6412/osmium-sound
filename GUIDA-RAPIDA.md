# 🎵 Osmium Sound — Guida Rapida

*[Read in English](QUICKSTART.md)*

Come installare e iniziare a usare Osmium Sound sul tuo mini-PC x86.

## 🚀 Installazione

1. **Procurati l'immagine di installazione.** Scarica l'ultima ISO da
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases)
   e scrivila su una chiavetta USB da 8&nbsp;GB o più con
   [balenaEtcher](https://etcher.balena.io/), Rufus o `dd`, oppure usa
   **Osmium Flasher** (app desktop per Windows/Linux, vedi
   [`flasher/`](flasher/README.md)): scarica l'immagine corrente, ne verifica
   la firma e scrive la chiavetta per te.
2. **Avvia il mini-PC dalla chiavetta.** Lo schermo mostra solo un QR code —
   non serve mai mouse o tastiera. Scansionalo con il telefono: il telefono si
   collega all'hotspot Wi-Fi aperto `Osmium-Setup-XXXX` del dispositivo (senza
   password) e la pagina di installazione si apre da sola (captive portal; se
   non succede, apri `http://10.42.0.1`). Se il dispositivo è collegato via
   cavo puoi aprire direttamente il suo indirizzo di rete — il QR lo mostra.
3. **Concludi dal telefono**: scegli il disco di destinazione, conferma la
   cancellazione, avvia. Lo schermo mostra l'avanzamento in sola lettura e si
   riavvia da solo al termine.

> **Selezione del disco.** Scegli dal telefono su quale disco installare;
> viene cancellato solo quello — nulla viene cancellato senza conferma.
> L'installer configura GRUB per la modalità firmware con cui la macchina è
> stata avviata (UEFI è il percorso collaudato e consigliato; il BIOS legacy è
> supportato ma meno testato).

> **Provala in modalità live.** Scegli **Try Osmium Sound (no install)** nel
> menu di avvio per far partire il kiosk direttamente dalla chiavetta USB —
> senza scrivere nulla sul disco. Se non fa l'accesso automatico, usa
> `hifi` / `hifi` alla schermata di login.

**Nota:** la ISO serve solo per la prima installazione. Tutti gli aggiornamenti
successivi (interfaccia, sistema, OS, Lyrion) arrivano automaticamente via
**OTA** dalla schermata Impostazioni o dall'amministrazione web — non serve
riflashare nulla.

## 🧙 Primo avvio

Al primo avvio dopo l'installazione, lo schermo chiede una sola cosa: la
**rete**. Scegli il tuo Wi-Fi sul touchscreen e digita la password; con il cavo
Ethernet non c'è nulla da fare. Lo schermo mostra poi l'indirizzo del
dispositivo (`http://<ip>`): aprilo dal telefono o dal computer ed esegui la
**configurazione guidata** dal browser, in quest'ordine:

1. **Lingua** (inglese di default, italiano disponibile).
2. **Ripristino da backup, oppure configurazione da zero.** Caricando un file
   di backup precedente (e la relativa passphrase, se cifrato) si ripristinano
   rete, audio, Lyrion, sorgenti e fuso orario in un colpo solo; il dispositivo
   si riavvia per applicarli e i passi successivi vengono saltati.
3. **Rete** — di solito già fatta dallo schermo; il passo resta per chi vuole
   spostare su Wi-Fi un dispositivo collegato via cavo.
4. **Aggiornamenti** — un controllo aggiornamenti obbligatorio, così la
   procedura guidata gira sul software più recente (può riavviare il
   dispositivo una volta; la procedura riprende da sola).
5. **Nome del dispositivo** (`<nome>.local`, usato anche per il multiroom).
6. **Modalità del dispositivo** — *con schermo*, *headless* o *solo server*
   (vedi sotto).
7. **Puntatore del mouse** on/off (solo con schermo), **uscita audio**
   (DAC/HDMI).
8. **Lyrion** — esegui Lyrion Music Server su questo dispositivo, oppure
   punta a uno già presente in rete (rilevato automaticamente).
9. **Aspetto del player web** — tema **Osmium** o **Material** semplice, e i
   **servizi musicali** da attivare (Spotify, TIDAL, Qobuz, Deezer, radio, …).
10. **Account di amministrazione web** (utente + password — le credenziali per
    la pagina di amministrazione e, volendo, per SSH).
11. **Fuso orario**, poi **sorgenti musicali** (condivisioni NAS o dischi
    interni, facoltative — una chiavetta USB viene rilevata da sola).

Una volta terminato dal browser, il dispositivo prosegue da solo — nessun
pulsante da premere sullo schermo. Da lì in poi l'app si apre direttamente
sulla schermata principale (oppure resta headless, a seconda di cosa hai
scelto).

## 🎮 Come si usa

- **Libreria / Radio / App**: l'interfaccia per Lyrion Music Server —
  libreria locale, radio internet, Scopri (mix casuali, artisti simili,
  biografie) e servizi di streaming (Deezer, Qobuz, TIDAL, Spotify e altri)
  tramite i **plugin di Lyrion**. I plugin scelti in fase di configurazione
  sono già pronti; gli altri si installano dalla web UI di Lyrion
  (Impostazioni → Plugin) e compaiono da soli, senza aggiornare l'app.
- **In riproduzione**: copertina grande, trasporto e volume, VU meter analogico
  opzionale, indicatore bit-perfect / ReplayGain.
- **CD**: inserisci un CD audio per riprodurlo, oppure rippalo in FLAC
  taggati dentro una delle tue sorgenti.
- **Impostazioni** (a schermo): lingua, Lyrion (server, aspetto del player
  web, rescan), sorgenti musicali, uscita audio, riproduzione, multiroom,
  sveglia, rete, web remote (QR per aprire il player web dal telefono; note per
  iPhone), SSH, puntatore, risoluzione UI, frequenza di aggiornamento,
  modalità schermo, fuso orario, info di sistema, aggiornamenti (canale
  Prod/Dev, "Aggiorna ora"), controlli di sistema (riavvio, spegnimento,
  reset di fabbrica, reset password web), licenze di terze parti.

## 📱 App companion Android

Controlla Osmium Sound dal telefono — sfoglia la libreria, gestisci
riproduzione e coda, regola il volume, cambia uscita audio, gestisci
multiroom, aggiornamenti e backup. Abbina scansionando il QR code da
Impostazioni sul dispositivo. Distribuita come APK firmato o tramite il
nostro repo F-Droid self-hosted — non è sul Play Store. Dettagli su
[osmiumsound.it](https://osmiumsound.it/#android) e in
[COMPANION_APP.md](COMPANION_APP.md).

## 🔧 Problemi comuni

- **Il front-end Lyrion non carica**: verifica il server Lyrion in
  Impostazioni → Lyrion (locale, default `http://localhost:9000`, oppure il
  server esterno scelto) e che il servizio sia attivo.
- **Sorgenti streaming/radio mancanti**: installa il plugin corrispondente
  dalla web UI di Lyrion (Impostazioni → Plugin).
- **Audio non funziona**: controlla il dispositivo audio selezionato in
  Impostazioni → Audio e che il DAC sia riconosciuto; in modalità solo server
  il player è spento di proposito.
- **`hifiplayer.local` non risponde**: usa l'indirizzo IP mostrato in
  Impostazioni → Rete (o nella schermata di configurazione) — i nomi `.local`
  sono ambigui quando in rete c'è più di un'unità.

## 🖥️ Modalità dispositivo, headless e amministrazione web

Osmium Sound può funzionare **con schermo** (kiosk touchscreen), **headless**
(senza schermo, gestito da browser o dall'app companion) oppure **solo
server** (senza schermo *e* senza riproduzione audio in locale — per un
dispositivo il cui unico compito è servire Lyrion Music Server ad altri
player Osmium in casa).

**Amministrazione web:** apri **http://\<ip-del-dispositivo\>** (oppure
`http://hifiplayer.local`) da qualsiasi browser della tua rete e accedi con
l'account creato durante la configurazione. È HTTP semplice sulla rete locale
— nessun avviso di certificato, nessun cloud di mezzo. Da lì: rete, audio,
sorgenti (NAS/dischi interni, condivisione SMB), impostazioni di riproduzione
e schermo, Lyrion (aspetto del player web, rescan, aggiornamenti Lyrion),
aggiornamenti, backup (su richiesta, pianificati, cifrati; ripristino), SSH
(con il login Linux che scegli), accesso remoto Tailscale, abbinamento della
companion, account, reset di fabbrica e una scheda Debug per l'assistenza.

**Gestire un dispositivo headless o solo server:** l'amministrazione web qui
sopra, l'**app companion**, oppure il player web di Lyrion su
**http://\<ip-del-dispositivo\>:9000** (la voce "Osmium Admin" nel suo menu
apre anche l'amministrazione web).

**Cambiare modalità in seguito:** Impostazioni → *Modalità schermo* contiene
entrambi gli interruttori — con schermo ⇄ headless, e player acceso ⇄ spento
(spento = solo server) — a schermo se ne hai uno, oppure dall'amministrazione
web/app companion se non ne hai. È questo il modo per riaccendere lo schermo
su un'unità headless.

**Rete persa su un'unità già configurata:** se il dispositivo non raggiunge
più nessuna rete, rialza l'hotspot `Osmium-Setup-XXXX` con una pagina di sola
configurazione di rete, così puoi collegarlo a un nuovo Wi-Fi dal telefono;
l'hotspot sparisce appena la rete torna.

**Reset di fabbrica:** Impostazioni → *Controlli di sistema* (a schermo),
oppure dall'amministrazione web (reinserendo la password). Cancella tutte le
impostazioni **e l'account di amministrazione web**, elimina i backup
memorizzati, poi riavvia tornando alla configurazione del primo avvio.

## 📚 Altre risorse

- **[README.md](README.md)**: panoramica, funzioni e specifiche
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: dettagli tecnici, API, sviluppo locale
- **[Manuale utente](https://osmiumsound.it/manual.html)** sul sito
- Note di rilascio: in ogni [Release GitHub](https://github.com/adri6412/osmium-sound/releases) e nella schermata Aggiornamenti ("novità")

---

**Buon ascolto con Osmium Sound! 🎶**
