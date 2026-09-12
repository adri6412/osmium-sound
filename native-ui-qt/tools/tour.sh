#!/bin/bash
# Giro completo delle schermate, per le fotografie: ogni passo lascia un PNG in
# /tmp/shots. Va lanciato sul dispositivo con hifi-qt attivo e HIFI_DEV=1.
cd "$(dirname "$0")/.."
D=bash\ tools/devcmd.sh
c() { bash tools/devcmd.sh "$@" >/dev/null; }
s() { bash tools/devcmd.sh "shot /tmp/shots/$1.png" >/dev/null; echo "  $1"; }

echo "— schermata principale e libreria"
c "eval app.setExpanded(false)" "eval app.main.browser.openTab(0)" "eval app.main.browser.navHome()" "sleep 2"; s 01-principale
c "tap 460 175" "sleep 3.5"; s 02-artisti
c "tap 600 103" "sleep 0.4" "type be" "sleep 1.5"; s 03-artisti-ricerca
c "eval app.main.browser.navHome()" "sleep 1.5" "tap 682 155" "sleep 4"; s 04-album
c "hold 1000 300" "move 1000 360" "sleep 0.8"; s 05-album-indice-az
c "release 1000 360" "sleep 0.5" "eval app.main.browser.goView(3, 'Brani', '578')" "sleep 3"; s 06-brani
c "hold 700 160" "sleep 1.3" "release 700 160" "sleep 1"; s 07-menu-contestuale
c "tap 200 400" "sleep 1" "eval app.main.browser.navHome()" "sleep 1.5" "tap 903 155" "sleep 3.5"; s 08-cartelle
c "eval app.main.browser.navHome()" "sleep 1.5" "tap 461 280" "sleep 3"; s 09-playlist
c "eval app.main.browser.navHome()" "sleep 1.5" "tap 682 280" "sleep 3.5"; s 10-preferiti
c "tap 478 20" "sleep 4"; s 11-radio
c "tap 569 20" "sleep 4"; s 12-app
c "eval app.main.browser.rowTap(0, false)" "sleep 4"; s 13-app-voci
c "tap 662 20" "sleep 3.5"; s 14-scopri
c "tap 966 63" "sleep 4"; s 15-scopri-generi
c "tap 966 63" "sleep 1"

echo "— in riproduzione e pannelli"
c "eval app.main.browser.openTab(0)" "sleep 1" "tap 305 20" "sleep 3"; s 20-in-riproduzione
c "tap 903 31" "sleep 3"; s 21-in-riproduzione-testi
c "tap 903 31" "sleep 1.5" "tap 945 31" "sleep 3"; s 22-coda
c "tap 754 561" "sleep 1.5" "type Serata" "sleep 1"; s 23-salva-playlist
c "key esc" "sleep 1" "key esc" "sleep 1.5" "tap 987 31" "sleep 2"; s 24-timer-spegnimento
c "key esc" "sleep 1.5" "eval app.keyboard.openText('Nome della playlist', 'Serata', false, null)" "sleep 1.5"; s 25-tastiera
c "eval app.keyboard.close(false)" "sleep 1.5" "eval app.saver.show(true)" "sleep 2"; s 26-salvaschermo
c "tap 500 300" "sleep 2" "eval app.setExpanded(false)" "sleep 1.5"

echo "— impostazioni"
c "tap 727 20" "sleep 2.5"; s 30-impostazioni
c "scroll 680 400 600" "sleep 1.2"; s 31-impostazioni-2
c "scroll 680 400 600" "sleep 1.2"; s 32-impostazioni-3
c "scroll 680 400 -1400" "sleep 1"
for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  c "eval app.settings.openSection($i)" "sleep 2.5"; s "4$(printf %02d $i)-sezione-$i"
done

echo "— sorgenti musicali: le quattro fasce"
c "eval app.settings.openSection(1)" "sleep 2" "eval app.settings.activate({arg:'0'}, 'band')" "sleep 3"; s 60-sorgenti-attive
c "eval app.settings.activate({arg:'1'}, 'band')" "sleep 2" "eval app.settings.activate({arg:'0'}, 'band_add')" "sleep 2"; s 61-sorgenti-aggiungi-smb
c "eval app.settings.activate({arg:'1'}, 'band_add')" "sleep 3"; s 62-sorgenti-dischi-interni
c "eval app.settings.activate({arg:'2'}, 'band_add')" "sleep 3.5"; s 63-sorgenti-cartella-locale
c "eval app.settings.activate({arg:'2'}, 'band')" "sleep 3"; s 64-sorgenti-playlist
c "eval app.settings.activate({arg:'3'}, 'band')" "sleep 3"; s 65-sorgenti-condivise

echo "— dialoghi"
c "eval app.settings.openSection(14)" "sleep 2" "eval app.settings.activate({}, 'timezone')" "sleep 2.5"; s 70-scelta-fuso
c "eval app.dlg.finishPick(-1)" "sleep 1.5" "eval app.settings.openSection(17)" "sleep 2" "eval app.settings.activate({}, 'reboot')" "sleep 2"; s 71-conferma
c "eval app.dlg.finishOk(false)" "sleep 1.5" "eval app.settings.openSection(16)" "sleep 3" "eval app.settings.activate({}, 'upd_changelog')" "sleep 2"; s 72-novita
c "eval app.dlg.close()" "sleep 1.5" "eval app.settings.openSection(6)" "sleep 2" "eval app.settings.activate({}, 'wifi_panel')" "sleep 5"; s 73-wifi
c "eval app.dlg.finishWifi(false)" "sleep 1.5" "eval app.main.browser.openTab(0)" "sleep 1.5"
echo "fatto: $(ls /tmp/shots/*.png | wc -l) fotografie"
