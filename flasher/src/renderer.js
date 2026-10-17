'use strict';

/* Osmium Flasher — renderer. No Node access here; everything goes through the
   `flasher` bridge exposed by preload.js.

   The app walks the whole install, not just the stick: prepare the USB stick,
   boot the mini PC from it, then run the on-device installer. Phases 2 and 3
   happen on the other machine, so they are instructions rather than actions --
   but leaving them out is what left people stranded halfway.

   Two choices up front: the channel (production, stable; development, the
   newest work) and the image -- the installer ISO, which puts Osmium Sound on
   the PC's internal disk, or the USB image, which runs it from the stick. The
   later screens follow the image: elements marked data-only="iso" or
   data-only="usb" show for that one alone. */

// ── strings ────────────────────────────────────────────────────────────────
const STRINGS = {
  en: {
    'step.stick': 'USB stick',
    'step.boot': 'Boot',
    'step.install': 'Install',
    'step.setup': 'Setup',

    'welcome.title': 'Osmium Sound on a mini PC',
    'welcome.lead': 'This app writes a USB stick for the mini PC: either to install Osmium Sound on its internal disk, or to run it straight from the stick. Nothing on this computer is touched.',
    'welcome.needTitle': 'What you need',
    'welcome.need1': 'An x86 mini PC to turn into the player.',
    'welcome.need2': 'A USB stick of at least 8 GB. Everything already on it will be erased. To run Osmium Sound from the stick, a fast USB 3 one is best.',
    'welcome.need3': 'This computer, connected to the internet — the image is about 1 GB.',
    'welcome.useLocal': 'Use an image already on this computer instead',
    'welcome.restore': 'Restore a USB stick to factory condition',
    'welcome.loading': 'Looking for the current image…',
    'welcome.localPicked': 'Local image — not signature-checked',
    'welcome.channelTitle': 'Which version?',
    'welcome.prod': 'Production',
    'welcome.prodDesc': 'Stable: the version recommended for everyone.',
    'welcome.dev': 'Development',
    'welcome.devDesc': 'Has the latest new features, but may be unstable.',
    'welcome.kindTitle': 'How will you use it?',
    'welcome.iso': 'Install on the PC\'s internal disk',
    'welcome.isoDesc': 'The stick is only for installing: Osmium Sound is copied onto the mini PC\'s internal disk, which is erased. Then the stick comes out.',
    'welcome.usb': 'Use it straight from the USB stick',
    'welcome.usbDesc': 'Osmium Sound starts and runs from the stick: the PC\'s internal disk is not touched. The stick stays plugged in.',
    'welcome.notYet': 'Not available yet for this choice.',
    'welcome.notYetShort': 'not out yet',

    'select.title': 'Choose the USB stick',
    'select.lead': 'Only removable drives are listed. Your system disk is never shown.',
    'select.empty': 'Insert a USB stick — it will appear here automatically.',
    'select.readonly': 'write-protected',
    'select.toosmall': 'too small for this image',

    'confirm.title': 'Last check before erasing',
    'confirm.warnTitle': 'Everything on this drive will be destroyed.',
    'confirm.warnBody': 'The image is written to the raw device, so existing partitions and files cannot be recovered afterwards.',
    'confirm.oversize': 'This drive is larger than 256 GB — unusual for a USB stick. I have checked it is not an external hard drive.',

    'work.downloading': 'Downloading the image',
    'work.checking': 'Checking the image',
    'work.unpacking': 'Unpacking the image',
    'work.leadUnpack': 'The USB image travels compressed: it is unpacked here, on this computer, before it is written. This takes a few minutes.',
    'work.flashing': 'Writing to the USB stick',
    'work.verifying': 'Verifying what was written',
    'work.starting': 'Waiting for permission…',
    'work.leadDownload': 'The image is about 1 GB. An interrupted download resumes where it stopped.',
    'work.leadElevate': 'Your system will ask for your password: writing to a raw device needs administrator rights.',
    'work.leadDirect': 'Getting ready. This drive can be written to without administrator rights, so nothing will be asked of you.',
    'work.leadFlash': 'Do not unplug the stick.',
    'work.formatting': 'Restoring the USB stick',
    'work.leadFormat': 'Writing a fresh partition table and an empty FAT32 volume. This takes a few seconds.',

    'boot.ready': 'The USB stick is ready.',
    'boot.title': 'Boot the mini PC from the stick',
    'boot.s1': 'Plug the stick into the mini PC and switch it on.',
    'boot.s3': 'Restart and tap the boot-menu key repeatedly — usually F11, F12, Esc or Del, depending on the motherboard.',
    'boot.s4': 'Pick the USB stick from the list, then choose <strong>Install Osmium Sound</strong> from the menu that appears.',
    'boot.s4Usb': 'Pick the USB stick from the list: Osmium Sound starts by itself.',
    'boot.keepTitle': 'Leave the stick plugged in',
    'boot.keep': 'From now on the stick is Osmium Sound\'s disk: the system, your settings and the updates all live on it. Take it out and the mini PC goes back to whatever it ran before.',
    'boot.tryTitle': 'Just want to try it?',
    'boot.try': 'Write the stick again choosing <strong>Use it straight from the USB stick</strong>: Osmium Sound then runs from the stick, without touching the mini PC\'s disk.',
    'boot.troubleTitle': 'The stick is not in the boot menu',
    'boot.trouble': 'Check that USB booting is enabled in the firmware setup, and try the other USB ports: rear ones are often more reliable than front ones. The image is signed for Secure Boot, so that is not the problem — but if nothing else works, a fussy firmware may still need Secure Boot turned off.',

    'install.title': 'Install on the mini PC',
    'install.s1': 'On the welcome screen, pick <strong>Choose disk</strong> and select the target disk from the list.',
    'install.s2': 'Read the warning, then confirm with <strong>Erase and install</strong>.',
    'install.s3': 'Progress is shown on screen. When it finishes, the mini PC restarts on its own.',
    'install.s4': 'Once it has restarted, unplug the USB stick.',
    'install.warnTitle': 'Choosing a disk erases it permanently.',
    'install.warn': 'Double-check you picked the right one before confirming, especially if the mini PC has more than one disk attached.',
    'install.phoneTitle': 'No keyboard or mouse on the mini PC?',
    'install.phone': 'A QR code sits in the top-right corner of the screen from the very first frame. Scan it and run the whole install from your phone — the mini PC\'s screen mirrors the progress either way.',

    'setup.title': 'Set up Osmium Sound',
    'setup.s1': 'On the first start the stick makes room for your data by itself. It takes a moment: do not switch the mini PC off.',
    'setup.s2': 'Then the guided setup appears: language, network, the player\'s name and the rest. Follow it on the screen, or from your phone by scanning the QR code.',
    'setup.s3': 'When it is done, Osmium Sound is ready to play.',
    'setup.laterTitle': 'Want it on the internal disk later?',
    'setup.later': 'Come back here and choose <strong>Install on the PC\'s internal disk</strong>.',
    'finishUsb.title': 'Osmium Sound is ready on the stick',
    'finishUsb.lead': 'If the mini PC does not start from the stick by itself, put USB first in the firmware\'s boot order, or use the boot-menu key every time.',
    'finishUsb.nextTitle': 'Updates arrive by themselves',
    'finishUsb.next': 'The interface, the operating system and the music server are updated over the air from the Settings screen, straight on the stick. Do not use the stick for anything else: it holds the system and your settings.',
    'finish.title': 'That is the whole install',
    'finish.lead': 'The mini PC restarts into Osmium Sound on its own. Give it a moment on first boot while it sets itself up.',
    'finish.nextTitle': 'You will not need the stick again',
    'finish.next': 'Every later update — interface, operating system and music server — arrives automatically over the air from the Settings screen. The stick is only ever needed for a first install, so you can safely reuse it.',
    'finish.another': 'Write another USB stick',

    'restore.title': 'Restore this USB stick?',
    'restore.warnTitle': 'Everything on this drive will be erased.',
    'restore.warnBody': 'The stick is rebuilt as a single empty FAT32 partition covering its full capacity — the state it was in before an installer image was written to it. Nothing on it can be recovered afterwards.',
    'restored.title': 'The USB stick is back to normal',
    'restored.lead': 'It is now a single empty FAT32 volume spanning the whole stick, and your computer will show it as an ordinary removable drive again.',

    'error.title': 'It did not work',
    'error.support': 'If it keeps failing, write to support@osmiumsound.it with the detail above.',

    'btn.continue': 'Continue',
    'btn.back': 'Back',
    'btn.cancel': 'Cancel',
    'btn.write': 'Erase and write',
    'btn.close': 'Close',
    'btn.retry': 'Try again',
    'btn.restore': 'Erase and restore',

    'err.ENET': 'The download could not be completed. Check the connection and try again.',
    'err.EHTTP': 'The server did not return the image.',
    'err.EMANIFEST': 'The list of available images could not be read.',
    'err.ENOSIG': 'This image is not signed, so it was refused.',
    'err.EBADSIG': 'The image signature is not valid — it was refused.',
    'err.EBADSUM': 'The downloaded image was corrupt and has been discarded. Try again.',
    'err.ENAMEMISMATCH': 'The signature belongs to a different image — it was refused.',
    'err.ECANCELLED': 'Cancelled.',
    'err.EDENIED': 'Permission was refused, so nothing was written.',
    'err.EGONE': 'The USB stick was disconnected.',
    'err.ESYSTEM': 'That drive looks like a system disk, so it was refused.',
    'err.EREADONLY': 'The USB stick is write-protected.',
    'err.ETOOSMALL': 'The USB stick is too small for this image.',
    'err.EWRITE': 'Writing failed. Try a different USB stick or a different port.',
    'err.EPERM_MACOS': 'macOS refused access to the drive. Its raw disk devices are guarded by a permission that applies even to administrators, and it is granted by code signature — which this app, being unsigned, does not have a stable one of. Open System Settings → Privacy & Security → Full Disk Access, add Osmium Flasher, and try again. If that does not help, write the stick with balenaEtcher instead: it is notarized, so macOS grants it what it needs.',
    'err.ECRASH': 'The writer stopped unexpectedly.',
    'err.EELEVATE': 'The elevated step failed without reporting a reason.',
    'err.EOPEN': 'The drive could not be opened for writing. Close anything using it and try again.',
    'err.EFORMAT': 'The stick could not be reformatted.',
    'err.ENOSIZE': 'The drive did not report its size, so it cannot be reformatted.',
    'err.EUNEXPECTED': 'Something went wrong that was not anticipated.',
    'err.ENOTYET': 'This version is not available yet.',
    'err.EIMAGE': 'The image could not be unpacked: it may be damaged. Try again.',
    'err.ENOSPACE': 'This computer does not have enough free space: unpacking the USB image needs about 5 GB.',
    'error.report': 'Report file:',
  },

  it: {
    'step.stick': 'Chiavetta',
    'step.boot': 'Avvio',
    'step.install': 'Installazione',
    'step.setup': 'Configurazione',

    'welcome.title': 'Osmium Sound su un mini PC',
    'welcome.lead': 'Questa app prepara una chiavetta USB per il mini PC: per installare Osmium Sound sul suo disco interno, oppure per usarlo direttamente dalla chiavetta. Su questo computer non viene toccato nulla.',
    'welcome.needTitle': 'Cosa serve',
    'welcome.need1': 'Un mini PC x86 da trasformare nel lettore.',
    'welcome.need2': 'Una chiavetta USB da almeno 8 GB. Tutto quello che contiene verrà cancellato. Per usare Osmium Sound dalla chiavetta è meglio una veloce, USB 3.',
    'welcome.need3': "Questo computer, connesso a internet — l'immagine pesa circa 1 GB.",
    'welcome.useLocal': "Usa invece un'immagine già presente su questo computer",
    'welcome.restore': 'Riporta una chiavetta alle condizioni di fabbrica',
    'welcome.loading': "Ricerca dell'immagine corrente…",
    'welcome.localPicked': 'Immagine locale — firma non verificata',
    'welcome.channelTitle': 'Quale versione?',
    'welcome.prod': 'Produzione',
    'welcome.prodDesc': 'Stabile: la versione consigliata per tutti.',
    'welcome.dev': 'Sviluppo',
    'welcome.devDesc': 'Contiene le ultime novità, ma può essere instabile.',
    'welcome.kindTitle': 'Come vuoi usarlo?',
    'welcome.iso': 'Installa sul disco interno del PC',
    'welcome.isoDesc': 'La chiavetta serve solo per installare: Osmium Sound viene copiato sul disco interno del mini PC, che viene cancellato. Poi la chiavetta si toglie.',
    'welcome.usb': 'Usa direttamente dalla chiavetta USB',
    'welcome.usbDesc': 'Osmium Sound parte e funziona dalla chiavetta: il disco interno del PC non viene toccato. La chiavetta resta sempre collegata.',
    'welcome.notYet': 'Non ancora disponibile per questa scelta.',
    'welcome.notYetShort': 'non ancora uscita',

    'select.title': 'Scegli la chiavetta USB',
    'select.lead': 'Sono elencate solo le unità rimovibili. Il disco di sistema non compare mai.',
    'select.empty': 'Inserisci una chiavetta USB — comparirà qui automaticamente.',
    'select.readonly': 'protetta da scrittura',
    'select.toosmall': "troppo piccola per quest'immagine",

    'confirm.title': 'Ultimo controllo prima di cancellare',
    'confirm.warnTitle': "Tutto il contenuto di questa unità verrà distrutto.",
    'confirm.warnBody': "L'immagine viene scritta direttamente sul dispositivo: le partizioni e i file esistenti non saranno più recuperabili.",
    'confirm.oversize': 'Questa unità supera i 256 GB — insolito per una chiavetta. Ho verificato che non è un disco esterno.',

    'work.downloading': "Download dell'immagine",
    'work.checking': "Controllo dell'immagine",
    'work.unpacking': "Decompressione dell'immagine",
    'work.leadUnpack': "L'immagine per chiavetta viaggia compressa: viene decompressa qui, su questo computer, prima di essere scritta. Ci vuole qualche minuto.",
    'work.flashing': 'Scrittura sulla chiavetta',
    'work.verifying': 'Verifica di quanto scritto',
    'work.starting': "In attesa dell'autorizzazione…",
    'work.leadDownload': "L'immagine pesa circa 1 GB. Un download interrotto riprende da dove si era fermato.",
    'work.leadElevate': 'Il sistema chiederà la password: scrivere direttamente su un dispositivo richiede i permessi di amministratore.',
    'work.leadDirect': "Preparazione in corso. Questa unità è scrivibile senza permessi di amministratore, quindi non ti verrà chiesto nulla.",
    'work.leadFlash': 'Non scollegare la chiavetta.',
    'work.formatting': 'Ripristino della chiavetta',
    'work.leadFormat': 'Scrittura di una nuova tabella delle partizioni e di un volume FAT32 vuoto. Richiede pochi secondi.',

    'boot.ready': 'La chiavetta è pronta.',
    'boot.title': 'Avvia il mini PC dalla chiavetta',
    'boot.s1': 'Collega la chiavetta al mini PC e accendilo.',
    'boot.s3': 'Riavvia e premi ripetutamente il tasto del menu di avvio — di solito F11, F12, Esc o Canc, a seconda della scheda madre.',
    'boot.s4': "Scegli la chiavetta dall'elenco, poi seleziona <strong>Install Osmium Sound</strong> dal menu che compare.",
    'boot.s4Usb': "Scegli la chiavetta dall'elenco: Osmium Sound parte da solo.",
    'boot.keepTitle': 'Lascia la chiavetta collegata',
    'boot.keep': 'Da ora la chiavetta è il disco di Osmium Sound: sistema, impostazioni e aggiornamenti stanno lì. Se la togli, il mini PC torna al sistema che aveva prima.',
    'boot.tryTitle': 'Vuoi solo provarlo?',
    'boot.try': 'Riscrivi la chiavetta scegliendo <strong>Usa direttamente dalla chiavetta USB</strong>: Osmium Sound gira dalla chiavetta, senza toccare il disco del mini PC.',
    'boot.troubleTitle': "La chiavetta non compare nel menu di avvio",
    'boot.trouble': "Verifica che l'avvio da USB sia abilitato nel setup del firmware e prova le altre porte USB — quelle posteriori sono spesso più affidabili di quelle frontali. L'immagine è firmata per il Secure Boot, quindi non è quello il problema — ma se non si sblocca in altro modo, un firmware schizzinoso potrebbe volerlo comunque disattivato.",

    'install.title': 'Installa sul mini PC',
    'install.s1': 'Nella schermata di benvenuto scegli <strong>Choose disk</strong> e seleziona il disco di destinazione dall\'elenco.',
    'install.s2': 'Leggi l\'avviso, poi conferma con <strong>Erase and install</strong>.',
    'install.s3': "L'avanzamento è mostrato a schermo. Al termine il mini PC si riavvia da solo.",
    'install.s4': 'Quando si è riavviato, scollega la chiavetta USB.',
    'install.warnTitle': 'La scelta del disco lo cancella in modo permanente.',
    'install.warn': 'Verifica di aver scelto quello giusto prima di confermare, soprattutto se il mini PC ha più di un disco collegato.',
    'install.phoneTitle': 'Niente tastiera o mouse sul mini PC?',
    'install.phone': "Un QR code compare nell'angolo in alto a destra dello schermo fin dal primo istante. Scansionalo e guida tutta l'installazione dal telefono — lo schermo del mini PC mostra comunque l'avanzamento.",

    'setup.title': 'Configura Osmium Sound',
    'setup.s1': 'Al primo avvio la chiavetta prepara da sola lo spazio per i tuoi dati. Ci vuole un momento: non spegnere il mini PC.',
    'setup.s2': 'Poi compare la configurazione guidata: lingua, rete, nome del lettore e il resto. Puoi seguirla sullo schermo oppure dal telefono, inquadrando il QR code.',
    'setup.s3': 'Alla fine Osmium Sound è pronto a suonare.',
    'setup.laterTitle': 'Più avanti lo vuoi sul disco interno?',
    'setup.later': 'Torna qui e scegli <strong>Installa sul disco interno del PC</strong>.',
    'finishUsb.title': 'Osmium Sound è pronto sulla chiavetta',
    'finishUsb.lead': "Se il mini PC non parte da solo dalla chiavetta, metti l'USB al primo posto nell'ordine di avvio del firmware, oppure usa ogni volta il tasto del menu di avvio.",
    'finishUsb.nextTitle': 'Gli aggiornamenti arrivano da soli',
    'finishUsb.next': 'Interfaccia, sistema operativo e server musicale si aggiornano via OTA dalla schermata Impostazioni, direttamente sulla chiavetta. Non usarla per altro: contiene il sistema e le tue impostazioni.',
    'finish.title': "L'installazione finisce qui",
    'finish.lead': 'Il mini PC si riavvia da solo su Osmium Sound. Al primo avvio lascialo lavorare qualche istante mentre si configura.',
    'finish.nextTitle': 'La chiavetta non ti servirà più',
    'finish.next': 'Tutti gli aggiornamenti successivi — interfaccia, sistema operativo e server musicale — arrivano automaticamente via OTA dalla schermata Impostazioni. La chiavetta serve solo per la prima installazione, quindi puoi tranquillamente riutilizzarla.',
    'finish.another': "Scrivi un'altra chiavetta",

    'restore.title': 'Ripristinare questa chiavetta?',
    'restore.warnTitle': "Tutto il contenuto di questa unità verrà cancellato.",
    'restore.warnBody': "La chiavetta viene ricostruita come una singola partizione FAT32 vuota che copre tutta la capacità — lo stato in cui si trovava prima che ci fosse scritta un'immagine di installazione. Nulla sarà più recuperabile.",
    'restored.title': 'La chiavetta è tornata normale',
    'restored.lead': 'Ora è un unico volume FAT32 vuoto esteso a tutta la chiavetta, e il computer tornerà a mostrarla come una comune unità rimovibile.',

    'error.title': 'Non ha funzionato',
    'error.support': 'Se continua a fallire, scrivi a support@osmiumsound.it allegando il dettaglio qui sopra.',

    'btn.continue': 'Continua',
    'btn.back': 'Indietro',
    'btn.cancel': 'Annulla',
    'btn.write': 'Cancella e scrivi',
    'btn.close': 'Chiudi',
    'btn.retry': 'Riprova',
    'btn.restore': 'Cancella e ripristina',

    'err.ENET': 'Il download non è stato completato. Controlla la connessione e riprova.',
    'err.EHTTP': "Il server non ha restituito l'immagine.",
    'err.EMANIFEST': 'Non è stato possibile leggere la lista delle immagini disponibili.',
    'err.ENOSIG': "Quest'immagine non è firmata ed è stata rifiutata.",
    'err.EBADSIG': "La firma dell'immagine non è valida: rifiutata.",
    'err.EBADSUM': "L'immagine scaricata era corrotta ed è stata eliminata. Riprova.",
    'err.ENAMEMISMATCH': "La firma appartiene a un'altra immagine: rifiutata.",
    'err.ECANCELLED': 'Annullato.',
    'err.EDENIED': 'Autorizzazione negata: non è stato scritto nulla.',
    'err.EGONE': 'La chiavetta è stata scollegata.',
    'err.ESYSTEM': "Quell'unità sembra un disco di sistema ed è stata rifiutata.",
    'err.EREADONLY': 'La chiavetta è protetta da scrittura.',
    'err.ETOOSMALL': "La chiavetta è troppo piccola per quest'immagine.",
    'err.EWRITE': "Scrittura fallita. Prova con un'altra chiavetta o un'altra porta USB.",
    'err.EPERM_MACOS': "macOS ha negato l'accesso all'unità. I suoi dispositivi disco grezzi sono protetti da un permesso che vale anche per gli amministratori, e viene concesso in base alla firma del codice — che quest'app, non essendo firmata, non ha in forma stabile. Apri Impostazioni di Sistema → Privacy e sicurezza → Accesso completo al disco, aggiungi Osmium Flasher e riprova. Se non basta, scrivi la chiavetta con balenaEtcher: essendo notarizzato, macOS gli concede quello che serve.",
    'err.ECRASH': 'Il processo di scrittura si è interrotto in modo imprevisto.',
    'err.EELEVATE': "Il passaggio con privilegi è fallito senza indicarne il motivo.",
    'err.EOPEN': "Non è stato possibile aprire l'unità in scrittura. Chiudi ciò che la sta usando e riprova.",
    'err.EFORMAT': 'Non è stato possibile riformattare la chiavetta.',
    'err.ENOSIZE': "L'unità non riporta la propria dimensione, quindi non può essere riformattata.",
    'err.EUNEXPECTED': 'Si è verificato un problema non previsto.',
    'err.ENOTYET': 'Questa versione non è ancora disponibile.',
    'err.EIMAGE': "Non è stato possibile decomprimere l'immagine: potrebbe essere danneggiata. Riprova.",
    'err.ENOSPACE': "Su questo computer non c'è abbastanza spazio libero: per decomprimere l'immagine per chiavetta servono circa 5 GB.",
    'error.report': 'File di diagnosi:',
  },
};

let lang = 'en';
const t = (key) => (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    // Several strings carry <strong>/<code> for emphasis, so this is innerHTML.
    // Everything here is our own literal text, never anything from outside.
    el.innerHTML = t(el.dataset.i18n);
  });
  document.getElementById('langEn').classList.toggle('on', lang === 'en');
  document.getElementById('langIt').classList.toggle('on', lang === 'it');
  render();
}

// ── helpers ────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function bytes(n) {
  if (!n) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function duration(seconds) {
  if (!seconds || !isFinite(seconds)) return '';
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`;
}

// ── state ──────────────────────────────────────────────────────────────────
// Which wizard phase each screen belongs to, for the stepper.
const PHASE_OF = {
  welcome: 'stick', select: 'stick', confirm: 'stick', work: 'stick',
  boot: 'boot',
  install: 'install', finish: 'install',
  restored: 'stick',   // restoring is a stick job; the stepper is hidden for it
};
const PHASE_ORDER = ['stick', 'boot', 'install'];

const state = {
  screen: 'welcome',
  mode: 'install',      // 'install' walks the whole wizard; 'restore' just reformats
  catalog: null,        // { prod: {ok, version, iso, usb}, dev: … } from the manifests
  channel: 'prod',      // 'prod' | 'dev'
  kind: 'iso',          // 'iso' (install on the internal disk) | 'usb' (run from the stick)
  release: null,        // the image the two choices point at, when there is one
  local: null,          // locally picked image, bypasses the manifest
  imagePromise: null,   // download+verify running in the background
  imageResult: null,
  drives: [],
  selected: null,
  writing: false,
  elevated: true,      // finché l'helper non dice il contrario
  phase: null,
  progress: null,
  error: null,
  lastPhase: 'stick',   // keeps the stepper steady while the error screen shows
};

function show(screen) {
  state.screen = screen;
  if (PHASE_OF[screen]) state.lastPhase = PHASE_OF[screen];
  document.querySelectorAll('.screen').forEach((el) => el.classList.remove('on'));
  $('screen' + screen[0].toUpperCase() + screen.slice(1)).classList.add('on');
  document.querySelector('main').scrollTop = 0;
  render();
}

/** The image the two choices point at, or null when that one is not out. */
function chosenRelease() {
  const ch = state.catalog && state.catalog[state.channel];
  return ch && ch.ok ? ch[state.kind] || null : null;
}

/** Bytes that end up on the stick: the unpacked disk for the USB image. */
function bytesOnStick() {
  if (state.local) return state.local.size;
  if (state.release) return state.release.rawSize || state.release.size;
  return 0;
}

// ── rendering ──────────────────────────────────────────────────────────────
function renderKind() {
  document.querySelectorAll('[data-only]').forEach((el) => {
    el.hidden = el.dataset.only !== state.kind;
  });
  // Running from the stick has no install phase: the third step is the setup.
  $('stepInstallLabel').textContent = t(state.kind === 'usb' ? 'step.setup' : 'step.install');
}

function renderStepper() {
  // Restoring a stick is not part of the three-phase install, so the wizard's
  // progress indicator would only be misleading there.
  const stepper = document.getElementById('stepper');
  stepper.hidden = state.mode === 'restore';
  if (stepper.hidden) return;

  const current = PHASE_OF[state.screen] || state.lastPhase;
  const at = PHASE_ORDER.indexOf(current);
  document.querySelectorAll('.stepper .step').forEach((el) => {
    const i = PHASE_ORDER.indexOf(el.dataset.phase);
    el.classList.toggle('on', i === at);
    el.classList.toggle('done', i < at);
  });
}

function renderFooter() {
  const next = $('btnNext');
  const back = $('btnBack');
  const cancel = $('btnCancel');

  back.hidden = true;
  cancel.hidden = true;
  next.hidden = false;
  next.className = 'btn primary';
  next.disabled = false;

  switch (state.screen) {
    case 'welcome':
      next.textContent = t('btn.continue');
      next.disabled = !(state.release || state.local);
      break;
    case 'select':
      back.hidden = false;
      back.textContent = t('btn.back');
      next.textContent = t('btn.continue');
      next.disabled = !state.selected;
      break;
    case 'confirm': {
      back.hidden = false;
      back.textContent = t('btn.back');
      next.textContent = t(state.mode === 'restore' ? 'btn.restore' : 'btn.write');
      next.className = 'btn destroy';
      const needsAck = state.selected && state.selected.oversize;
      next.disabled = Boolean(needsAck) && !$('oversizeAck').checked;
      break;
    }
    case 'work':
      next.hidden = true;
      cancel.hidden = state.writing;      // a write in flight must not be torn off
      cancel.textContent = t('btn.cancel');
      break;
    case 'boot':
      next.textContent = t('btn.continue');
      break;
    case 'install':
      back.hidden = false;
      back.textContent = t('btn.back');
      next.textContent = t('btn.continue');
      break;
    case 'finish':
    case 'restored':
      next.textContent = t('btn.close');
      break;
    case 'error':
      back.hidden = false;
      back.textContent = t('btn.close');
      next.textContent = t('btn.retry');
      break;
    default:
      break;
  }
}

function renderChoices() {
  const cat = state.catalog;
  const verOf = (channel) => {
    const ch = cat && cat[channel];
    if (!ch) return '';
    return ch.ok ? ch.version : ch.code === 'ENOTYET' ? t('welcome.notYetShort') : '—';
  };
  $('prodVer').textContent = verOf('prod');
  $('devVer').textContent = verOf('dev');
  document.querySelectorAll('#channelChoices .choice').forEach((el) => {
    el.classList.toggle('sel', !state.local && el.dataset.channel === state.channel);
    el.classList.toggle('dev', el.dataset.channel === 'dev');
  });
  document.querySelectorAll('#kindChoices .choice').forEach((el) => {
    el.classList.toggle('sel', el.dataset.kind === state.kind);
  });
}

function renderWelcome() {
  renderChoices();
  $('releaseCard').classList.toggle('missing', false);
  if (state.local) {
    $('releaseTag').textContent = t('welcome.localPicked');
    $('releaseSize').textContent = bytes(state.local.size);
  } else if (state.release) {
    $('releaseTag').textContent = state.release.name;
    $('releaseSize').textContent = bytes(state.release.size);
  } else if (state.catalog) {
    $('releaseTag').textContent = t('welcome.notYet');
    $('releaseSize').textContent = '';
    $('releaseCard').classList.toggle('missing', true);
  } else {
    $('releaseTag').textContent = t('welcome.loading');
    $('releaseSize').textContent = '';
  }
}

function renderDrives() {
  const list = $('driveList');
  const empty = $('driveEmpty');
  const imageSize = bytesOnStick();

  list.textContent = '';
  empty.hidden = state.drives.length > 0;

  state.drives.forEach((d) => {
    const tooSmall = imageSize > 0 && d.size > 0 && d.size < imageSize;
    const blocked = d.isReadOnly || tooSmall;

    const btn = document.createElement('button');
    btn.className = 'drive' + (state.selected && state.selected.device === d.device ? ' sel' : '');
    if (blocked) btn.setAttribute('disabled', '');

    const box = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = d.description || d.displayName;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = d.device + (d.mountpoints.length ? ' · ' + d.mountpoints.join(', ') : '');
    box.append(name, meta);

    if (blocked) {
      const warn = document.createElement('div');
      warn.className = 'warn';
      warn.textContent = d.isReadOnly ? t('select.readonly') : t('select.toosmall');
      box.append(warn);
    }

    const cap = document.createElement('span');
    cap.className = 'cap';
    cap.textContent = bytes(d.size);

    btn.append(box, cap);
    if (!blocked) {
      btn.addEventListener('click', () => {
        state.selected = d;
        render();
      });
    }
    list.append(btn);
  });
}

function renderConfirm() {
  if (!state.selected) return;
  const restoring = state.mode === 'restore';
  $('confirmTitle').textContent = t(restoring ? 'restore.title' : 'confirm.title');
  $('confirmWarnTitle').textContent = t(restoring ? 'restore.warnTitle' : 'confirm.warnTitle');
  $('confirmWarnBody').textContent = t(restoring ? 'restore.warnBody' : 'confirm.warnBody');
  $('confirmTarget').textContent =
    `${state.selected.description || state.selected.displayName} — ${bytes(state.selected.size)} (${state.selected.device})`;
  $('oversizeWrap').hidden = !state.selected.oversize;
}

function renderWork() {
  const phase = state.phase || 'starting';
  $('workTitle').textContent = t('work.' + phase) || '';
  $('workLead').textContent =
    phase === 'downloading' ? t('work.leadDownload')
      : phase === 'unpacking' ? t('work.leadUnpack')
      : phase === 'starting' ? t(state.elevated ? 'work.leadElevate' : 'work.leadDirect')
        : phase === 'formatting' ? t('work.leadFormat')
          : t('work.leadFlash');

  const bar = $('workBar');
  const p = state.progress;
  let pct = null;
  if (p && p.total) pct = (p.received / p.total) * 100;
  else if (p && typeof p.percentage === 'number') pct = p.percentage;

  if (pct === null) {
    bar.classList.add('indeterminate');
    bar.firstElementChild.style.width = '';
    $('workLeft').textContent = '';
    $('workRight').textContent = '';
    return;
  }

  bar.classList.remove('indeterminate');
  bar.firstElementChild.style.width = Math.max(0, Math.min(100, pct)).toFixed(1) + '%';

  const done = p.received !== undefined ? p.received : p.position;
  const total = p.total !== undefined ? p.total : p.size;
  $('workLeft').textContent = `${bytes(done)} / ${bytes(total)} · ${pct.toFixed(0)}%`;
  $('workRight').textContent = [
    p.speed ? `${bytes(p.speed)}/s` : '',
    p.eta ? duration(p.eta) : '',
  ].filter(Boolean).join(' · ');
}

function renderError() {
  const err = state.error || {};
  $('errorLead').textContent = t('err.' + err.code) || err.message || '';
  const lines = [`${err.code || 'EUNKNOWN'}: ${err.message || ''}`];
  if (err.progressFile) lines.push('', `${t('error.report')} ${err.progressFile}`);
  $('errorDetail').textContent = lines.join('\n');
}

function render() {
  renderKind();
  renderStepper();
  renderWelcome();
  if (state.screen === 'select') renderDrives();
  if (state.screen === 'confirm') renderConfirm();
  if (state.screen === 'work') renderWork();
  if (state.screen === 'error') renderError();
  renderFooter();
}

function fail(err) {
  state.error = err;
  state.writing = false;
  show('error');
}

// ── flow ───────────────────────────────────────────────────────────────────
async function loadManifest() {
  const res = await window.flasher.fetchManifest();
  state.catalog = res.ok ? res.catalog : null;
  // Production that cannot be read is the one real failure: the development
  // channel simply may not be out yet.
  const prod = state.catalog && state.catalog.prod;
  if (prod && !prod.ok && prod.code !== 'ENOTYET') {
    $('releaseError').hidden = false;
    $('releaseError').textContent = t('err.' + prod.code) || prod.message;
  } else {
    $('releaseError').hidden = true;
  }
  if (!state.local) state.release = chosenRelease();
  render();
}

/** A different image was chosen: whatever was fetched for the old one goes. */
function choose(channel, kind) {
  if (channel) state.channel = channel;
  if (kind) state.kind = kind;
  const next = chosenRelease();
  const changed = (next && next.name) !== (state.release && state.release.name);
  if (state.local) {
    state.local = null;
  } else if (!changed) {
    render();
    return;
  }
  if (state.imagePromise) window.flasher.cancelImage();
  state.imagePromise = null;
  state.imageResult = null;
  state.release = next;
  render();
}

function startImagePrepare() {
  if (state.local || state.imagePromise || !state.release) return;
  const release = state.release;
  const promise = window.flasher.prepareImage(release).then((res) => {
    // A choice changed meanwhile: this result belongs to an image no longer wanted.
    if (res.ok && state.imagePromise === promise) state.imageResult = res;
    return res;
  });
  state.imagePromise = promise;
}

/** Back to the top of phase 1, keeping the image already downloaded. */
function restartForAnotherStick() {
  state.selected = null;
  state.error = null;
  state.progress = null;
  state.phase = null;
  show('select');
}

async function runRestore() {
  show('work');
  state.writing = true;
  state.phase = 'starting';
  state.progress = null;
  render();

  const res = await window.flasher.restore({ devicePath: state.selected.device });

  state.writing = false;
  if (!res.ok) return fail(res);
  show('restored');
}

async function runWrite() {
  show('work');
  state.phase = state.local ? 'starting' : 'downloading';
  state.progress = null;
  render();

  // Wait for the background download+verify that started when we left the
  // welcome screen; a hand-picked file has nothing to wait for.
  let img = state.local;
  if (!img) {
    const res = await state.imagePromise;
    if (!res.ok) {
      state.imagePromise = null;   // let a retry start a fresh attempt
      return fail(res);
    }
    img = res;
  }

  state.writing = true;
  state.phase = 'starting';
  state.progress = null;
  state.elevated = true;
  render();

  const res = await window.flasher.write({
    devicePath: state.selected.device,
    imagePath: img.file,
    imageSize: img.size,
    verify: true,
  });

  state.writing = false;
  if (!res.ok) return fail(res);
  show('boot');
}

// ── wiring ─────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  const info = await window.flasher.info();
  $('appVersion').textContent = 'v' + info.version;
  lang = /^it/i.test(info.locale || '') ? 'it' : 'en';
  applyLanguage();

  $('langEn').addEventListener('click', () => { lang = 'en'; applyLanguage(); });
  $('langIt').addEventListener('click', () => { lang = 'it'; applyLanguage(); });

  window.flasher.onImageProgress((p) => {
    if (state.writing) return;              // the write's own progress takes over
    state.phase = p.phase;
    state.progress = p;
    if (state.screen === 'work') renderWork();
  });

  window.flasher.onDrives((list) => {
    state.drives = list;
    // A stick pulled out mid-selection must not stay selected.
    if (state.selected && !list.some((d) => d.device === state.selected.device)) {
      state.selected = null;
      if (state.screen === 'confirm') show('select');
    }
    if (state.screen === 'select') render();
  });

  window.flasher.onWriteProgress((event) => {
    // Sent before anything is written: on a drive we can already open for
    // writing there is no password prompt coming, so we must not announce one.
    if (event.type === 'elevation') {
      state.elevated = event.elevated !== false;
      if (state.screen === 'work') renderWork();
      return;
    }
    if (event.type === 'progress') {
      state.phase = event.stage === 'verifying' ? 'verifying'
        : event.stage === 'formatting' ? 'formatting' : 'flashing';
      state.progress = event;
    } else if (event.type === 'stage') {
      state.phase = event.stage === 'formatting' ? 'formatting' : 'flashing';
    }
    if (state.screen === 'work') renderWork();
  });

  document.querySelectorAll('#channelChoices .choice').forEach((el) => {
    el.addEventListener('click', () => choose(el.dataset.channel, null));
  });
  document.querySelectorAll('#kindChoices .choice').forEach((el) => {
    el.addEventListener('click', () => choose(null, el.dataset.kind));
  });

  $('useLocal').addEventListener('click', async () => {
    const res = await window.flasher.pickImage();
    if (!res.ok) return;
    if (state.imagePromise) window.flasher.cancelImage();
    state.imagePromise = null;
    state.imageResult = null;
    state.local = res;
    state.release = null;
    // The file says which of the two it is, and so which screens follow.
    state.kind = /\.img(\.xz)?$/i.test(res.file) ? 'usb' : 'iso';
    $('releaseError').hidden = true;
    render();
  });

  $('anotherStick').addEventListener('click', restartForAnotherStick);

  $('restoreStick').addEventListener('click', () => {
    state.mode = 'restore';
    state.selected = null;
    window.flasher.watchDrives();
    show('select');
  });
  $('oversizeAck').addEventListener('change', renderFooter);

  $('btnNext').addEventListener('click', () => {
    switch (state.screen) {
      case 'welcome':
        startImagePrepare();
        window.flasher.watchDrives();
        show('select');
        break;
      case 'select':
        show('confirm');
        break;
      case 'confirm':
        if (state.mode === 'restore') runRestore(); else runWrite();
        break;
      case 'boot':
        show('install');
        break;
      case 'install':
        show('finish');
        break;
      case 'finish':
      case 'restored':
        window.close();
        break;
      case 'error':
        state.error = null;
        show(state.selected ? 'select' : 'welcome');
        if (!state.local && !state.release) loadManifest();
        break;
      default:
        break;
    }
  });

  $('btnBack').addEventListener('click', () => {
    if (state.screen === 'select') { state.mode = 'install'; show('welcome'); }
    else if (state.screen === 'confirm') show('select');
    else if (state.screen === 'install') show('boot');
    else if (state.screen === 'error') window.close();
  });

  $('btnCancel').addEventListener('click', async () => {
    await window.flasher.cancelImage();
    state.imagePromise = null;
    show('select');
  });

  await loadManifest();
});
