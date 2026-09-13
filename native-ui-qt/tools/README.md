# Strumenti di sviluppo della UI Qt

Il Dell (192.168.0.133) compila e mostra la UI vera; per lavorare senza
apparecchio c'è un chroot Debian 13 con lo stesso Qt 6.8.2, sotto Xvfb, contro
un finto apparecchio in Python.

- `chroot-setup.sh` — prepara `/srv/trixie` (debootstrap + Qt + Xvfb + Mesa).
  Nel contenitore di sviluppo non si possono montare /proc e /dev: apt e Qt
  funzionano lo stesso; i sorgenti si copiano con rsync (`dev-build.sh`).
- `dev-build.sh` — rsync di `native-ui-qt/` in `/srv/trixie/build/hifi-qt` e `make`.
- `mockctl.sh` — (ri)avvia `mock-server.py` (Lyrion :9000, api :8000, sources :8080, VU :9001).
- `dev-run.sh` — Xvfb :99 + hifi-qt (xcb, llvmpipe) nel chroot; `MODE=1280x720`, `ARGS="--expanded"`.
- `dev-cmd.sh` — comandi al canale di collaudo (`/tmp/hifi-qt.cmd` nel chroot):
  `tap X Y`, `hold/move/release X Y`, `touch down|move|up X Y` (finto touchscreen), `scroll X Y DY`,
  `type testo`, `key esc|enter|...`, `eval <js sulla radice>` (es. `eval app.setExpanded(true)`),
  `sleep N`, `shot` → `$HIFI_DEV_DIR/$OUT`. Le coordinate sono della tela 1024x600.
  🚨 mouse e tocco passano dal livello QPA (`qt6-base-private-dev` nel chroot), come un mouse o un
  pannello veri: un `QMouseEvent` costruito a mano e mandato alla finestra non tiene la presa fra un
  evento e l'altro, e i trascinamenti non diventavano mai scorrimenti. Il primo evento dopo l'avvio
  puo' andare perso (stato del puntatore su xcb): premettere un `move`.
- `mock-server.py` — scenari via ambiente: `MOCK_LONG_QUEUE=1` (40 brani in coda),
  `MOCK_SHARED_LMS=N` (Lyrion altrui: prima solo un telefono, il nostro "Osmium" compare dopo N s),
  `MOCK_PLAYERS=1` (altri due player sul server, ognuno col suo now playing: per il selettore di player;
  riavviare il mock senza la variabile simula il telefono che se ne va).
- `devrun.sh` — sul Dell: ferma la UI in C e avvia hifi-qt su eglfs (`MODE=720`);
  `devrun.sh stop` ripristina. Lo stesso canale `/tmp/hifi-qt.cmd` e `kill -USR1` → `/tmp/hifi-qt.png`.
- `../sync.sh` — copia sorgenti+icone sul Dell e compila là.
- `../install.sh` — installa in /opt/hifi-qt e registra l'unità systemd (vedi file).

🚨 mai scrivere il pattern di `pkill -f` nella riga di comando esterna: pkill
uccide anche la shell chiamante che lo contiene. Per questo `mockctl.sh` esiste.
