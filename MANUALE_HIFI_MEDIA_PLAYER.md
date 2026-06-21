# HiFi Media Player
## Manuale Utente e Installazione

---

## Indice
1. Introduzione
2. Contenuto della Confezione
3. Specifiche Tecniche
4. Setup Iniziale
5. Configurazione di Rete
6. Configurazione Audio
7. Utilizzo del Sistema
8. Aggiornamenti di Sistema
9. Troubleshooting
10. Assistenza Tecnica

---

## 1. Introduzione

Benvenuto nel tuo **HiFi Media Player**, un sistema audio digitale di alta qualità progettato per la riproduzione audio professionale e domestica.

Questo dispositivo combina:
- **Qualità Audio Superiore**: Supporto per audio ad alta risoluzione e DSD bit-perfect
- **Software Open Source**: Basato su Lyrion Music Server
- **Interfaccia Intuitiva**: Touchscreen responsive e controllabile da qualsiasi dispositivo della rete
- **Autonomo**: Progettato per funzionare in ambienti dedicati senza interventi costanti

### Caratteristiche Principali
- ✓ Supporto DSD over PCM (DoP) per DAC DSD-capable
- ✓ FLAC, WAV, ALAC, MP3, OggVorbis e altri formati audio
- ✓ Aggiornamenti over-the-air (OTA) firmware e sistema operativo
- ✓ Configurazione di rete wireless (WiFi) e via cavo (Ethernet)
- ✓ Selezione dinamica di dispositivi audio USB e onboard
- ✓ Accesso remoto tramite Lyrion Music Server

---

## 2. Contenuto della Confezione

Il tuo HiFi Media Player contiene:

| Componente | Descrizione |
|-----------|------------|
| **Unità Principale** | Streamer audio con hardware dedicato |
| **Alimentatore** | 24V DC, certificato CE |
| **Cavo Ethernet** | RJ45 Cat6 per connessione LAN |
| **Cavo USB** (opzionale) | Per collegamento DAC esterno USB |
| **Manuale Utente** | Questo documento |
| **Garanzia** | Certificato di garanzia 2 anni |
| **Scheda WiFi** (opzionale) | Se configurato con connettività wireless |

---

## 3. Specifiche Tecniche

### Hardware
- **Processore**: ARM Quad-core 64-bit
- **RAM**: 4GB LPDDR4
- **Storage**: 64GB eMMC con supporto OTA updates
- **Alimentazione**: 24V DC, max 15W
- **Connettività**:
  - Gigabit Ethernet 10/100/1000 Mbps
  - WiFi 802.11ac dual-band (opzionale)
  - USB 2.0/3.0 per DAC esterni

### Audio
- **Output Digitale**: S/PDIF Toslink, USB Audio Class 2.0
- **Formati Supportati**: 
  - PCM: 16-384 kHz, fino a 32-bit
  - DSD: DSD64, DSD128 (via DoP)
  - Compresso: FLAC, WAV, ALAC, MP3, OggVorbis, AAC, WMA
- **Bit-Perfect**: Supporto full bit-perfect con flag -D attivo
- **Latenza Audio**: < 100ms

### Ambiente Operativo
- **Temperatura**: 0°C - 40°C
- **Umidità**: 10% - 90% (non condensante)
- **Dimensioni**: 150mm × 100mm × 80mm
- **Peso**: ~800g

---

## 4. Setup Iniziale

### Passo 1: Posizionamento e Alimentazione

1. **Posizionare il dispositivo** in un luogo stabile, lontano da:
   - Fonti di calore (radiatori, forni)
   - Vibrazione e rumore meccanico
   - Campi elettromagnetici forti (antenne, inverter)
   - Luce diretta del sole

2. **Collegare l'alimentatore**:
   - Inserire il connettore DC nel retro del dispositivo (contrassegnato con ⚡)
   - Collegare l'alimentatore a una presa di corrente
   - Il LED frontale diventerà verde quando il sistema è avviato
   - **Attendere 2-3 minuti** per il boot completo del sistema

3. **Indicatori LED**:
   - 🟢 **Verde fisso**: Sistema pronto e connesso
   - 🟠 **Arancione**: Sistema in boot o aggiornamento
   - 🔴 **Rosso**: Errore di sistema (contattare assistenza)
   - ⚫ **Spento**: Dispositivo non alimentato

### Passo 2: Connessione di Rete (Opzionale)

**Via Ethernet (Consigliato)**:
1. Collegare il cavo Ethernet al jack RJ45 etichettato "LAN"
2. L'altro capo al vostro router/switch
3. Il sistema si configurerà automaticamente via DHCP
4. Attendere il LED verde stabile (30 secondi)

**Via WiFi**:
1. Sul display touchscreen, toccare **"WiFi Setup"**
2. Selezionare la vostra rete SSID
3. Inserire la password (se richiesta)
4. Attendere la connessione (LED verde stabile)

---

## 5. Configurazione di Rete

### Accesso all'Interfaccia Web

Una volta connesso alla rete, potete accedere al sistema da qualsiasi browser:

**Indirizzo**: http://**[indirizzo-IP-del-dispositivo]**:9000

Per trovare l'indirizzo IP:
1. Controllare il vostro router (sezione dispositivi connessi)
2. Oppure sul display del dispositivo (sezione Sistema Info)
3. Oppure tramite SSH: `ssh root@hifi-media-player.local`

### Configurazione WiFi Avanzata

**Se necessitate di IP statico o configurazione avanzata**:

1. Accedere all'interfaccia web
2. Menu **"Sistema" → "Rete" → "Configurazione Avanzata"**
3. Selezionare **"Static IP"** dal dropdown
4. Inserire:
   - **Indirizzo IP**: Es. 192.168.1.100
   - **Gateway**: Es. 192.168.1.1
   - **DNS Primario**: Es. 8.8.8.8
   - **DNS Secondario**: Es. 8.8.4.4
5. Fare clic su **"Applica"**
6. Il dispositivo si riavvierà con la nuova configurazione

### Risoluzione Problemi di Rete

**Il dispositivo non si connette a WiFi**:
- Verificare che la rete WiFi sia visibile e il segnale sia > -70 dBm
- Provare a immettere manualmente la password (evitare copia/incolla)
- Riavviare il dispositivo (menu Sistema → Riavvia)

**IP non assegnato via DHCP**:
- Verificare che il router supporti DHCP (solitamente attivo di default)
- Controllare se il firewall del router sta bloccando il dispositivo
- Usare un IP statico manualmente (vedi sopra)

---

## 6. Configurazione Audio

### Selezione del DAC (Digital-to-Analog Converter)

Il sistema supporta:
- **DAC Onboard**: Uscita stereo integrata (qualità buona)
- **DAC Esterno USB**: Per qualità audio superiore

#### Scegliere il DAC

1. Accedere all'interfaccia web
2. Menu **"Sistema" → "Audio" → "Dispositivi Audio"**
3. Vedrete una lista di dispositivi disponibili:
   - "Predefinito di sistema"
   - "Topping D50s" (o il vostro DAC USB)
   - etc.
4. **Selezionare il vostro DAC preferito**
5. Il sistema applicherà la configurazione in tempo reale

#### Abilitare DSD (Bit-Perfect)

Il sistema è configurato per **abilitare automaticamente la modalità DSD (DoP)** per ogni DAC:

1. Nel menu Audio, verificare che il DAC selezionato supporti DoP
2. L'icona 🎵 **DSD** apparirà accanto al nome del DAC se supportato
3. I file DSD verranno riprodotti in modalità bit-perfect (nessuna conversione PCM)

### Regolazione del Volume

**Via Interfaccia Web**:
1. Nel player, usare i bottoni **"−"** e **"+"** per il volume
2. Il volume è memorizzato per il DAC selezionato

**Via Lyrion Web Controller** (da qualsiasi device):
1. Accedere a: http://[indirizzo-IP]:9000/lyrion
2. Controllare il volume centralmente per tutte le zone

---

## 7. Utilizzo del Sistema

### Riproduzione Musicale

#### Via Interfaccia Locale (Touchscreen)

1. **Connettere una libreria musicale**:
   - Accedere a "Libreria" nel menu principale
   - Aggiungere una cartella locale (USB, storage esterno)
   - Oppure connettersi a un server UPnP/Airplay

2. **Navigare e Riprodurre**:
   - Selezionare Artista → Album → Canzone
   - Toccare il nome della canzone per iniziare la riproduzione
   - I controlli di trasporto (Play/Pausa) sono nel footer

3. **Creare Playlist**:
   - Menu "Playlist" → "Nuova Playlist"
   - Aggiungere canzoni trascinandole o toccando "Aggiungi"

#### Via Lyrion Music Server (Remoto)

Accedere dall'app Lyrion su smartphone/tablet:

1. **Download App**:
   - iOS: App Store → "Lyrion"
   - Android: Google Play → "Lyrion"

2. **Configurare il Server**:
   - Aprire l'app
   - Inserire l'indirizzo IP del dispositivo (trovato in Sistema Info)
   - La porta è normalmente 9000

3. **Controllare da Remoto**:
   - Selezionare le canzoni dal vostro smartphone
   - Controllare volume, pausa, skip dal dispositivo HiFi

#### Via AirPlay (da Apple Devices)

1. Su iPhone/iPad/Mac: Apri il Control Center (scorrere dall'alto)
2. Tocca "AirPlay Audio"
3. Seleziona il tuo "HiFi Media Player"
4. La musica verrà riprodotta sul DAC configurato

### Menu Sistema

**Sistema Info**:
- Versione firmware OS
- Versione Lyrion Music Server
- Indirizzo IP e configurazione rete
- Stato memoria e storage
- Temperatura del processore

**Audio**:
- Selezione DAC/dispositivo output
- Visualizzazione informazioni audio (bitrate, sample rate, formato)
- Stato DSD (se supportato dal DAC)

**Rete**:
- Configurazione WiFi
- IP statico/DHCP
- DNS server
- Informazioni di connettività

**Sistema**:
- Accensione/Spegnimento
- Riavvio
- Ripristino impostazioni di default
- Informazioni garanzia

---

## 8. Aggiornamenti di Sistema

Il dispositivo controlla automaticamente gli aggiornamenti OTA (Over-The-Air) ogni 24 ore.

### Controllare Aggiornamenti Manualmente

1. Accedere all'interfaccia web
2. Menu **"Sistema" → "Aggiornamenti"**
3. Vedrete:
   - **Versione OS Attuale**
   - **Versione Lyrion Attuale**
   - **Aggiornamenti Disponibili** (se presenti)

### Installare un Aggiornamento

1. Se disponibile un aggiornamento, toccate **"Installa Aggiornamento"**
2. Il sistema mostrerà:
   - Numero versione
   - Note di rilascio (changelog)
3. Toccare **"Conferma"**
4. L'aggiornamento inizierà (il LED diventerà arancione)
5. **NON SPEGNERE IL DISPOSITIVO durante l'aggiornamento** ⚠️
6. Al termine, il dispositivo si riavvierà automaticamente
7. Attendere il LED verde stabile (2-3 minuti)

### Sicurezza degli Aggiornamenti

Tutti gli aggiornamenti sono:
- **Firmati crittograficamente** con chiave Ed25519
- **Verificati via SHA256** per integrità
- **Solo scaricati via HTTPS** (TLS 1.2+)
- **Verificati prima dell'esecuzione** (il sistema rifiuta aggiornamenti non validi)

Il dispositivo **non applicherà mai un aggiornamento non autentico**, anche se inviato da una sorgente malevola.

---

## 9. Troubleshooting

### Il dispositivo non si accende

- Verificare che l'alimentatore sia collegato correttamente
- Controllare che la presa di corrente sia funzionante (usare un altro dispositivo)
- Se il LED rimane spento, l'unità potrebbe avere un guasto: contattare l'assistenza

### Il LED è rosso (Errore)

- **Primo passo**: Riavviare il dispositivo (spegnere e riaccendere per 10 secondi)
- Se persiste, controllare i log:
  1. Accedere via SSH: `ssh root@hifi-media-player.local`
  2. Password: verificare le credenziali di default nella documentazione
  3. Eseguire: `journalctl -xe` per i log di sistema
  4. Eseguire: `systemctl status hifi-media-player` per lo stato del servizio

### Nessun audio in uscita

1. **Controllare il DAC**:
   - Menu Sistema → Audio → Verificare il DAC selezionato
   - Se USB, verificare che il DAC sia alimentato e riconosciuto
   - Provare a scollegare/ricollegare il DAC e attendere 5 secondi

2. **Controllare il volume**:
   - Verificare che il volume non sia al minimo (−∞ dB)
   - Aumentare il volume via interfaccia web o app

3. **Controllare i cavi**:
   - Verificare che il cavo dall'uscita audio del player vada all'amplificatore
   - Controllare se il cavo è danneggiato
   - Provare un cavo diverso

4. **Riavviare Squeezelite**:
   - Menu Sistema → "Riavvia Servizi Audio"
   - Attendere 5 secondi

### Distorsione o audio degradato

- **DAC USB disconnesso**: Verificare connessione USB, re-inserire il cavo
- **Bitrate troppo alto per la connessione**: Verificare che la WiFi abbia segnale stabile (> -70 dBm)
- **Processore sovraccarico**: Attendere che altri processi si completino
- **Buffer insufficiente**: Ridurre il bitrate dei file o usare connessione cablata

### Il dispositivo non si connette a WiFi

1. Verificare che il SSID sia visibile (non nascosto)
2. Verificare il segnale WiFi (il dispositivo necessita almeno −70 dBm)
3. Provare con il 5 GHz se disponibile (segnale più stabile)
4. Reimpostare la password WiFi:
   - Menu Rete → "Dimentica Rete"
   - Riconnettersi manualmente
5. Se persiste, usare Ethernet temporaneamente e:
   - SSH al dispositivo
   - Eseguire: `sudo systemctl restart NetworkManager`

### Aggiornamenti che non si installano

1. Verificare la connessione di rete (LED verde stabile)
2. Controllare lo spazio libero: Menu Sistema → Info → "Storage"
3. Se lo storage è pieno:
   - Scollegare librerie USB
   - Cancellare cache: Menu Sistema → "Pulisci Cache"
4. Provare di nuovo l'aggiornamento

### Impossibile accedere all'interfaccia web

1. Verificare che il dispositivo sia connesso alla rete (LED verde)
2. Assicurarsi che il PC/tablet sia sulla stessa rete
3. Provare a pinguare il dispositivo:
   ```
   ping hifi-media-player.local
   ```
   Se nessuna risposta, il dispositivo potrebbe non essere online
4. Se conosci l'IP diretto, provare:
   ```
   ping 192.168.1.XXX
   ```
5. Se comunque non raggiungibile, riavviare il dispositivo

---

## 10. Assistenza Tecnica

### Supporto Online

- **Sito Web**: https://hifi-media-player.it
- **Community Forum**: https://forum.hifi-media-player.it
- **GitHub Issues**: https://github.com/adri6412/hifi-media-player/issues

### Contatti Assistenza

- **Email**: support@hifi-media-player.it
- **Telefono**: +39 02 XXXX XXXX (Lun-Ven 9-17)
- **Chat Live**: Disponibile durante l'orario di ufficio

### Informazioni Garanzia

Il dispositivo è coperto da **garanzia 2 anni** dai difetti di fabbrica:

- Copre: Malfunzionamenti dovuti a difetti hardware/firmware
- Non copre: Danni da acqua, cadute, uso improprio, modifiche non autorizzate
- Per attivare garanzia: Conservare lo scontrino/fattura di acquisto

### Restituzione per Assistenza

Se il dispositivo ha un guasto coperto da garanzia:

1. Contattare l'assistenza con il numero seriale (etichetta posteriore)
2. Seguire le istruzioni per l'imballaggio sicuro
3. Spedire il dispositivo al nostro centro di assistenza
4. Riceverete il dispositivo riparato entro 5-7 giorni lavorativi

---

## Appendice: Specifiche Tecniche Avanzate

### Comandi SSH Utili

Se siete esperti di Linux, potete accedere al dispositivo via SSH:

```bash
ssh root@hifi-media-player.local
```

Comandi utili:
```bash
# Visualizzare lo stato del servizio
systemctl status hifi-media-player

# Restart del servizio
sudo systemctl restart hifi-media-player

# Visualizzare i log
journalctl -u hifi-media-player -f

# Informazioni di rete
ip addr show
nmcli device wifi list

# Spazio disco
df -h

# Temperatura del processore
cat /sys/class/thermal/thermal_zone0/temp
```

### File di Configurazione

- **Squeezelite Config**: `/etc/default/squeezelite`
- **Audio Devices**: `/proc/asound/cards`
- **Network Config**: `/etc/NetworkManager/conf.d/`
- **OS Updates**: `/etc/hifi-player/OS_VERSION`

### Riporto Errori Tecnici

Se scoprite un bug, per favore riportarlo:

1. **Raccogliere informazioni**:
   ```bash
   sudo systemctl status hifi-media-player
   journalctl -u hifi-media-player -n 50
   ```

2. **Creare un issue su GitHub**:
   - https://github.com/adri6412/hifi-media-player/issues/new
   - Descrivere il problema in dettaglio
   - Allegare i log (sopra)
   - Specificare la versione OS e Lyrion

---

## Changelog Versioni

### v1.5.0 (Attuale)
- ✅ Supporto DSD DoP automatico per tutti i DAC
- ✅ Interfaccia web redesignata
- ✅ Aggiornamenti firmware OTA con firma Ed25519
- ✅ Supporto WiFi dual-band 802.11ac
- ✅ Configurazione rete statica e DHCP

### v1.4.0
- Aggiunti controlli remoti Lyrion
- Miglioramenti stabilità audio

### v1.3.0
- Prime release stabile

---

**Grazie per aver scelto HiFi Media Player.**

*Per aggiornamenti futuri e annunci, visitate il nostro sito: https://hifi-media-player.it*

**Versione Manuale**: 1.5.0  
**Data**: Giugno 2026  
**Lingua**: Italiano  
**Supporto**: support@hifi-media-player.it
