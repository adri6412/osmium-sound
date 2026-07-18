# Analisi concorrenti e piano per 3 nuove feature

Analisi comparativa tra Osmium Sound e i principali prodotti concorrenti
(appliance/OS hi-fi per la riproduzione musicale), con un piano di
implementazione per le 3 feature a maggior impatto. Aggiornata a luglio 2026.

## 1. Panorama competitivo

| Prodotto | Modello | Punti di forza | Debolezze rispetto a Osmium |
|---|---|---|---|
| **Volumio 4** (Debian Bookworm) | Freemium — multiroom, TIDAL/Qobuz nativi, AI search e accesso remoto sono a pagamento (Premium) | UI curata, app mobili ufficiali, plugin store, Tidal Connect, stack Bluetooth riscritto, supporto NVMe | Le feature migliori richiedono abbonamento; touchscreen non è il focus |
| **moOde 9.x** (Raspberry Pi) | Gratuito, open source | Molto configurabile, cambio output senza riavvio, Wi-Fi hotspot di fallback, Bluetooth in/out, Deezer Connect renderer, DSP/EQ | Solo Raspberry Pi, UI meno rifinita, niente app companion nativa |
| **Daphile** (x86, come Osmium) | Gratuito, closed source | "Set and forget" su PC x86, LMS+squeezelite (stessa base di Osmium), **CD ripping integrato**, bit-perfect | UI datata, niente touchscreen, progetto poco attivo, closed source |
| **Roon 2.x** | Abbonamento (~150 $/anno) | Metadata ricchissimi, discovery con AI (Valence), Roon Radio, ARC (ascolto fuori casa con CarPlay/Android Auto), smart playlist | Costoso, richiede un Core potente, non è un'appliance standalone |
| **piCorePlayer** | Gratuito | Leggerissimo, stessa base LMS/squeezelite | Solo Pi, configurazione tecnica, niente UI moderna |

### Dove Osmium Sound è già competitivo

Buona parte di ciò che i concorrenti pubblicizzano è **già presente**: multiroom
con auto-discovery, DSP (EQ parametrico, crossfeed, room correction), bit-perfect
fino a DSD/192 kHz, streaming via plugin Lyrion (Spotify, TIDAL Connect, Qobuz,
Deezer), radio internet, testi (MusicArtistInfo), sveglia e sleep timer, app
companion Android con pairing QR, OTA firmati, **riproduzione CD** (plugin CD
Player + regole udev già nell'immagine), Samba/SMB/USB come sorgenti, VU meter
analogico. Tutto gratuito e open source — che di per sé è il principale
vantaggio competitivo rispetto a Volumio Premium e Roon.

### Gap reali individuati

1. **Bluetooth assente** (né ricezione dal telefono né uscita verso cuffie/casse BT) — Volumio 4 e moOde 9 lo hanno; è tra le feature più richieste in assoluto su questa categoria di prodotti.
2. **CD ripping assente** — il CD si può *riprodurre* ma non archiviare in libreria. Daphile (il concorrente più simile, x86+LMS) lo ha integrato; Volumio lo offre solo in Premium. Su hardware x86 con lettori USB economici è un differenziatore naturale.
3. **Nessuna discovery/mix intelligenti** — Roon vince quasi solo su questo (Valence, Roon Radio); Volumio Premium spinge la "AI search". L'ecosistema LMS offre già i mattoni (Don't Stop The Music, MusicArtistInfo, randomplay) ma non sono esposti nella UI touchscreen.

Gap minori (non selezionati, possibili follow-up): hotspot Wi-Fi di fallback per
il primo setup senza ethernet (moOde), accesso remoto fuori casa stile Roon ARC
(richiede infrastruttura relay/tunnel — costo e complessità alti), UI di
scrobbling Last.fm on-device.

---

## 2. Piano di implementazione — 3 feature

### Feature A — Audio Bluetooth (ricezione A2DP + uscita verso cuffie/casse BT)

**Obiettivo:** il telefono può riprodurre musica sull'appliance via Bluetooth; in
alternativa l'appliance può usare cuffie/speaker BT come uscita.

**Approccio tecnico:** BlueZ + **BlueALSA** (niente PulseAudio/PipeWire: la
catena bit-perfect ALSA di squeezelite resta intoccata quando il BT non è in uso).

Passi:
1. **Distro** — aggiungere `bluez`, `bluez-tools`, `bluez-alsa-utils` a
   `distro/config/package-lists/hifi.list.chroot`; unit systemd `bluealsa` e
   `bluealsa-aplay` (disabilitate di default); script in
   `distro/os-update/apply.d/` per portare i pacchetti sulle installazioni esistenti via OTA.
2. **Backend (`api_server.py`)** — nuove route:
   `GET /bluetooth/status`, `POST /bluetooth/set` (on/off + discoverable),
   `GET /bluetooth/devices` (associati/connessi), `POST /bluetooth/pair`,
   `POST /bluetooth/forget`. Implementazione via `bluetoothctl`/D-Bus.
3. **Modalità sink (telefono → appliance)** — agent "Just Works" (senza PIN);
   alla connessione A2DP: pausa del player Lyrion (via JSON-RPC locale) e avvio
   di `bluealsa-aplay` sul device ALSA corrente; alla disconnessione, ripristino.
4. **Modalità output (appliance → cuffie BT)** — opzione in Impostazioni che
   riscrive l'argomento `-o` di squeezelite verso il PCM `bluealsa` (stesso
   meccanismo già usato per il cambio DAC e per il "follow" multiroom).
5. **Frontend** — sezione "Bluetooth" in `src/pages/Settings.jsx`: toggle,
   modalità visibile con countdown, lista dispositivi con connetti/dimentica;
   badge sorgente "Bluetooth" sul Now Playing. Stringhe in `src/i18n/locales/`.
6. **Documentare il limite:** A2DP (SBC/AAC) non è bit-perfect — indicarlo in UI
   e nel README, coerentemente con la filosofia "off by default" già usata per il DSP.

**Rischi:** contesa del device ALSA tra squeezelite e bluealsa-aplay (mitigata
dalla pausa coordinata); variabilità dei dongle USB BT (documentare chipset consigliati).
**Stima:** 1,5–2 settimane. **Priorità: alta** (parità con Volumio/moOde).

### Feature B — CD ripping in libreria

**Obiettivo:** inserisci un CD, tocchi "Rippa", e l'album finisce taggato in
libreria con copertina. Parità con Daphile, gratis dove Volumio chiede il Premium.

**Approccio tecnico:** riusa l'infrastruttura esistente — le regole udev
`99-hifi-cdrom.rules` ci sono già, e `sources_server.py` ha già il pattern dei
job asincroni via `systemd-run` (usato per il format dei dischi).

Passi:
1. **Distro** — aggiungere `cdparanoia`, `flac`, `cd-discid` (e `python3-musicbrainzngs`)
   ai package list + script `apply.d` per l'OTA.
2. **Backend (`sources_server.py`)** — route (protette dal pairing token come le altre 🔒):
   `GET /api/cd/info` (TOC + lookup MusicBrainz: artista, album, tracce, cover;
   fallback offline "Unknown Album"), `POST /api/cd/rip` (avvia job asincrono),
   `GET /api/cd/rip/status` (traccia n/m, percentuale, errori), `POST /api/cd/eject`.
3. **Pipeline di rip** — `cdparanoia` → `flac` con tagging (mutagen) e cover
   embedded, output in `Artista/Album/NN - Titolo.flac` nella sorgente interna/USB
   scelta; a fine job, rescan Lyrion tramite il meccanismo `POST /api/apply` esistente.
4. **Frontend** — rilevamento disco (poll di `/api/cd/info` quando la pagina è
   attiva o evento su inserimento): banner "CD rilevato — Riproduci / Rippa";
   schermata di progresso con avanzamento per traccia e annulla.
5. **Companion Android** — stesso flusso via API 🔒 (fase 2, opzionale).

**Rischi:** dischi rovinati (cdparanoia gestisce il recovery, esporre gli errori
per traccia); lookup metadata senza rete (fallback + possibilità di ritaggare dopo).
**Stima:** ~1 settimana. **Priorità: media-alta** (differenziatore su x86).

### Feature C — Discovery e "Mix intelligenti" (risposta a Roon Radio / Volumio AI)

**Obiettivo:** la musica non si ferma a fine coda e la UI aiuta a scoprire:
"continua con musica simile", artisti simili, mix casuali, bio artista.

**Approccio tecnico:** nessun servizio cloud proprietario — si orchestrano i
plugin LMS maturi: **Don't Stop The Music** (DSTM), **MusicArtistInfo** (già
usato per i testi: espone anche similar artists e bio) e il built-in `randomplay`.
Tutto via JSON-RPC dal renderer (`src/utils/lyrionApi.js`), senza toccare le API root.

Passi:
1. **Provisioning plugin** — assicurare DSTM e MusicArtistInfo installati/abilitati
   di default (stessa via usata oggi per i plugin Lyrion nel firstboot/OTA).
2. **`lyrionApi.js`** — nuovi metodi: get/set del provider DSTM per player
   (`playerpref plugin.dontstopthemusic:provider`), `similarArtists(artist)`,
   `artistBio(artist)` via `musicartistinfo`, `randomplay` (tracks/albums/artists).
3. **Now Playing** — toggle "Continua con musica simile" (attiva/disattiva DSTM
   sul player attivo), accanto allo sleep timer già presente.
4. **Sezione "Scopri"** — nuova voce nella Sidebar: pulsanti "Mix casuale" /
   "Album casuale", carosello "Artisti simili a ⟨artista in riproduzione⟩" con
   tap-to-play, pagina artista con bio e foto (MusicArtistInfo).
5. **i18n** — stringhe it/en per tutte le nuove superfici.

**Rischi:** dipendenza dalla qualità dei dati MusicArtistInfo su librerie piccole
(degradare con grazia nascondendo le sezioni vuote); DSTM richiede una libreria
locale ragionevole — con sole sorgenti streaming usare i provider DSTM dei plugin di streaming.
**Stima:** ~1 settimana. **Priorità: media** (è la feature che sposta la percezione da "player" a "esperienza", il terreno su cui vincono Roon e Volumio Premium).

### Ordine consigliato

1. **A — Bluetooth** (gap di parità più visibile, più richiesto)
2. **B — CD ripping** (rapida, riusa infrastruttura esistente, differenziatore x86)
3. **C — Discovery** (valore percepito alto, nessuna dipendenza dalle prime due)

Le tre feature sono indipendenti e possono procedere in parallelo su branch separati.
