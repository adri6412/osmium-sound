#!/usr/bin/env bash
# Osmium Sound — compone il pacchetto di prova OFFLINE della conversione A/B:
#   make-package.sh <versione> <hifi-system.tar.gz> <hifi-os.tar.gz> <hifi-image.raucb> <cartella-di-uscita>
# Produce <out>/osmium-ab-test-<ver>/ (driver + bundle + README) e il .tar corrispondente.
set -euo pipefail
VER="$1"; SYS="$2"; OS="$3"; IMG="$4"; OUT="$5"
HERE="$(cd "$(dirname "$0")" && pwd)"
P="$OUT/osmium-ab-test-$VER"
rm -rf "$P"; mkdir -p "$P"
cp "$SYS" "$P/hifi-system-$VER.tar.gz"
cp "$OS"  "$P/hifi-os-$VER.tar.gz"
cp "$IMG" "$P/hifi-image-$VER.raucb"
sed -e "s|__VERSION__|$VER|g" "$HERE/osmium-ab-test.sh.tmpl" > "$P/osmium-ab-test.sh"
chmod +x "$P/osmium-ab-test.sh"
cat > "$P/README.txt" <<TXT
Osmium Sound — prova offline della conversione A/B (RAUC), versione $VER
=====================================================================

Cosa c'è qui
  osmium-ab-test.sh          il driver: fa un passo per volta in base allo stato
  hifi-system-$VER.tar.gz   componenti di sistema (script hifi-ab-*, unità, API)
  hifi-os-$VER.tar.gz       payload OS (migrazione 0061: pacchetto rauc)
  hifi-image-$VER.raucb     immagine RAUC dello slot B (~1,2 GB)

Come si usa (sull'apparecchio, via SSH, come root)
  1. copia TUTTA la cartella, es.:  scp -r osmium-ab-test-$VER ssh@<ip>:/home/ssh/
  2. sudo sh osmium-ab-test.sh          → installa i pacchetti, pre-verifiche, pulizia, prepara
                                          e chiede di riavviare (1° riavvio: la root viene
                                          ristretta, nascono slot B e partizione dati; 1-5 min,
                                          NON SPEGNERE — sullo schermo il logo con la barra)
  3. sudo sh osmium-ab-test.sh          → (stato ready) semina /data, scrive l'immagine in B,
                                          attiva il selettore sulla ESP, chiede di riavviare (2°)
  4. dopo il riavvio parte l'immagine dallo slot B. Verifica:
        sudo sh osmium-ab-test.sh status
        rauc status
     Se B non si dichiara "buona" entro 10 minuti, l'apparecchio riavvia da solo e
     torna alla root legacy (che è ancora lì, intatta): rilancia lo script per vedere perché.

Spazio sulla root (apparecchi con disco da 16 GB)
  La pre-verifica misura quanto la root può restringersi (stima di resize2fs, prudente).
  Il bundle immagine da 1,3 GB copiato nella home CONTA: se la pre-verifica boccia per
  spazio, cancellalo dalla cartella, rilancia lo script (passo 2) e dopo la conversione
  ricopialo in /data/ab/ (sudo install -d -o \$USER /data/ab): il passo 3 lo trova da solo lì.
  Altre cose che liberano spazio: kernel di prova (apt purge), /var/lib/squeezeboxserver/cache.

Comandi utili
  sudo sh osmium-ab-test.sh status        stato, layout, grubenv, rauc
  sudo hifi-ab-precheck.sh                perché (non) si può convertire
  sudo hifi-ab-convert.sh status          idem, più dettagliato
  sudo rauc status mark-bad booted        dall'immagine: torna al legacy al prossimo riavvio
  cat /boot/efi/EFI/debian/abconvert.log  log della conversione fatta dall'initrd

Cosa NON viene toccato
  il binario GRUB/shim sulla ESP e le voci di avvio EFI (solo il file di testo
  grub.cfg sulla ESP, con lo stub di prima come ultimo ramo di ripiego); l'initrd di
  produzione (la conversione usa un initrd dedicato, poi rimosso).
TXT
( cd "$OUT" && tar cf "osmium-ab-test-$VER.tar" "osmium-ab-test-$VER" && sha256sum "osmium-ab-test-$VER.tar" > "osmium-ab-test-$VER.tar.sha256" )
ls -la "$P" "$OUT/osmium-ab-test-$VER.tar"
