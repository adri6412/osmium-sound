'use strict';

/* Osmium Flasher — renderer. No Node access here; everything goes through the
   `flasher` bridge exposed by preload.js.

   The app walks the whole install, not just the stick: prepare the USB stick,
   boot the mini PC from it, then run the on-device installer. Phases 2 and 3
   happen on the other machine, so they are instructions rather than actions --
   but leaving them out is what left people stranded halfway. */

// ── strings ────────────────────────────────────────────────────────────────
const STRINGS = {
  en: {
    'step.stick': 'USB stick',
    'step.boot': 'Boot',
    'step.install': 'Install',

    'welcome.title': 'Install Osmium Sound on a mini PC',
    'welcome.lead': 'Three steps: this app writes a USB stick, you boot the mini PC from it, and the installer on that machine does the rest. Nothing on this computer is touched.',
    'welcome.needTitle': 'What you need',
    'welcome.need1': 'An x86 mini PC to turn into the player.',
    'welcome.need2': 'A USB stick of at least 8 GB. Everything already on it will be erased.',
    'welcome.need3': 'This computer, connected to the internet — the image is about 1 GB.',
    'welcome.useLocal': 'Use an image already on this computer instead',
    'welcome.restore': 'Restore a USB stick to factory condition',
    'welcome.loading': 'Looking for the current image…',
    'welcome.localPicked': 'Local image — not signature-checked',

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
    'work.flashing': 'Writing to the USB stick',
    'work.verifying': 'Verifying what was written',
    'work.starting': 'Waiting for permission…',
    'work.leadDownload': 'The image is about 1 GB. An interrupted download resumes where it stopped.',
    'work.leadElevate': 'Your system will ask for your password: writing to a raw device needs administrator rights.',
    'work.leadFlash': 'Do not unplug the stick.',
    'work.formatting': 'Restoring the USB stick',
    'work.leadFormat': 'Writing a fresh partition table and an empty FAT32 volume. This takes a few seconds.',

    'boot.ready': 'The USB stick is ready.',
    'boot.title': 'Boot the mini PC from the stick',
    'boot.s1': 'Plug the stick into the mini PC and switch it on.',
    'boot.s2': 'Enter the firmware setup — usually <strong>Del</strong> or <strong>F2</strong> — and <strong>turn Secure Boot off</strong>, then save and exit. This is required on every machine: the image is not signed for Secure Boot, so it will not start with it enabled.',
    'boot.s3': 'Restart and tap the boot-menu key repeatedly — usually F11, F12, Esc or Del, depending on the motherboard.',
    'boot.s4': 'Pick the USB stick from the list, then choose <strong>Install Osmium Sound</strong> from the menu that appears.',
    'boot.tryTitle': 'Want a look first?',
    'boot.try': 'Choose <strong>Try Osmium Sound (no install)</strong> instead to run the interface straight from the stick, without writing anything to the mini PC\'s disk. If it does not log in by itself, use <code>hifi</code> / <code>hifi</code>.',
    'boot.troubleTitle': 'The stick is not in the boot menu',
    'boot.trouble': 'First make sure Secure Boot really is off — that is the usual reason. Then check that USB booting is enabled in the firmware setup, and try the other USB ports: rear ones are often more reliable than front ones.',

    'install.title': 'Install on the mini PC',
    'install.s1': 'On the welcome screen, pick <strong>Choose disk</strong> and select the target disk from the list.',
    'install.s2': 'Read the warning, then confirm with <strong>Erase and install</strong>.',
    'install.s3': 'Progress is shown on screen. When it finishes, the mini PC restarts on its own.',
    'install.s4': 'Once it has restarted, unplug the USB stick.',
    'install.warnTitle': 'Choosing a disk erases it permanently.',
    'install.warn': 'Double-check you picked the right one before confirming, especially if the mini PC has more than one disk attached.',
    'install.phoneTitle': 'No keyboard or mouse on the mini PC?',
    'install.phone': 'A QR code sits in the top-right corner of the screen from the very first frame. Scan it and run the whole install from your phone — the mini PC\'s screen mirrors the progress either way.',

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
    'err.ECRASH': 'The writer stopped unexpectedly.',
  },

  it: {
    'step.stick': 'Chiavetta',
    'step.boot': 'Avvio',
    'step.install': 'Installazione',

    'welcome.title': 'Installa Osmium Sound su un mini PC',
    'welcome.lead': "Tre passaggi: questa app scrive una chiavetta USB, tu avvii il mini PC da quella, e l'installer su quella macchina fa il resto. Su questo computer non viene toccato nulla.",
    'welcome.needTitle': 'Cosa serve',
    'welcome.need1': 'Un mini PC x86 da trasformare nel lettore.',
    'welcome.need2': 'Una chiavetta USB da almeno 8 GB. Tutto quello che contiene verrà cancellato.',
    'welcome.need3': "Questo computer, connesso a internet — l'immagine pesa circa 1 GB.",
    'welcome.useLocal': "Usa invece un'immagine già presente su questo computer",
    'welcome.restore': 'Riporta una chiavetta alle condizioni di fabbrica',
    'welcome.loading': "Ricerca dell'immagine corrente…",
    'welcome.localPicked': 'Immagine locale — firma non verificata',

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
    'work.flashing': 'Scrittura sulla chiavetta',
    'work.verifying': 'Verifica di quanto scritto',
    'work.starting': "In attesa dell'autorizzazione…",
    'work.leadDownload': "L'immagine pesa circa 1 GB. Un download interrotto riprende da dove si era fermato.",
    'work.leadElevate': 'Il sistema chiederà la password: scrivere direttamente su un dispositivo richiede i permessi di amministratore.',
    'work.leadFlash': 'Non scollegare la chiavetta.',
    'work.formatting': 'Ripristino della chiavetta',
    'work.leadFormat': 'Scrittura di una nuova tabella delle partizioni e di un volume FAT32 vuoto. Richiede pochi secondi.',

    'boot.ready': 'La chiavetta è pronta.',
    'boot.title': 'Avvia il mini PC dalla chiavetta',
    'boot.s1': 'Collega la chiavetta al mini PC e accendilo.',
    'boot.s2': "Entra nel setup del firmware — di solito <strong>Canc</strong> o <strong>F2</strong> — e <strong>disattiva il Secure Boot</strong>, poi salva ed esci. Serve su tutte le macchine: l'immagine non è firmata per il Secure Boot, quindi con quello attivo non parte.",
    'boot.s3': 'Riavvia e premi ripetutamente il tasto del menu di avvio — di solito F11, F12, Esc o Canc, a seconda della scheda madre.',
    'boot.s4': "Scegli la chiavetta dall'elenco, poi seleziona <strong>Install Osmium Sound</strong> dal menu che compare.",
    'boot.tryTitle': 'Vuoi prima dare un\'occhiata?',
    'boot.try': "Scegli invece <strong>Try Osmium Sound (no install)</strong> per far partire l'interfaccia direttamente dalla chiavetta, senza scrivere nulla sul disco del mini PC. Se non effettua l'accesso da solo, usa <code>hifi</code> / <code>hifi</code>.",
    'boot.troubleTitle': "La chiavetta non compare nel menu di avvio",
    'boot.trouble': "Per prima cosa assicurati che il Secure Boot sia davvero disattivato: è la causa più frequente. Poi verifica che l'avvio da USB sia abilitato nel setup del firmware e prova le altre porte USB — quelle posteriori sono spesso più affidabili di quelle frontali.",

    'install.title': 'Installa sul mini PC',
    'install.s1': 'Nella schermata di benvenuto scegli <strong>Choose disk</strong> e seleziona il disco di destinazione dall\'elenco.',
    'install.s2': 'Leggi l\'avviso, poi conferma con <strong>Erase and install</strong>.',
    'install.s3': "L'avanzamento è mostrato a schermo. Al termine il mini PC si riavvia da solo.",
    'install.s4': 'Quando si è riavviato, scollega la chiavetta USB.',
    'install.warnTitle': 'La scelta del disco lo cancella in modo permanente.',
    'install.warn': 'Verifica di aver scelto quello giusto prima di confermare, soprattutto se il mini PC ha più di un disco collegato.',
    'install.phoneTitle': 'Niente tastiera o mouse sul mini PC?',
    'install.phone': "Un QR code compare nell'angolo in alto a destra dello schermo fin dal primo istante. Scansionalo e guida tutta l'installazione dal telefono — lo schermo del mini PC mostra comunque l'avanzamento.",

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
    'err.ECRASH': 'Il processo di scrittura si è interrotto in modo imprevisto.',
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
  release: null,
  local: null,          // locally picked image, bypasses the manifest
  imagePromise: null,   // download+verify running in the background
  imageResult: null,
  drives: [],
  selected: null,
  writing: false,
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

// ── rendering ──────────────────────────────────────────────────────────────
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

function renderWelcome() {
  if (state.local) {
    $('releaseTag').textContent = t('welcome.localPicked');
    $('releaseSize').textContent = bytes(state.local.size);
  } else if (state.release) {
    $('releaseTag').textContent = state.release.version;
    $('releaseSize').textContent = bytes(state.release.size);
  } else {
    $('releaseTag').textContent = t('welcome.loading');
    $('releaseSize').textContent = '';
  }
}

function renderDrives() {
  const list = $('driveList');
  const empty = $('driveEmpty');
  const imageSize = state.imageResult ? state.imageResult.size
    : state.local ? state.local.size
      : state.release ? state.release.size : 0;

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
      : phase === 'starting' ? t('work.leadElevate')
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
  $('errorDetail').textContent = `${err.code || 'EUNKNOWN'}: ${err.message || ''}`;
}

function render() {
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
  if (res.ok) {
    state.release = res.release;
    $('releaseError').hidden = true;
  } else {
    $('releaseError').hidden = false;
    $('releaseError').textContent = t('err.' + res.code) || res.message;
  }
  render();
}

function startImagePrepare() {
  if (state.local || state.imagePromise) return;
  state.imagePromise = window.flasher.prepareImage(state.release).then((res) => {
    if (res.ok) state.imageResult = res;
    return res;
  });
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
    if (event.type === 'progress') {
      state.phase = event.stage === 'verifying' ? 'verifying'
        : event.stage === 'formatting' ? 'formatting' : 'flashing';
      state.progress = event;
    } else if (event.type === 'stage') {
      state.phase = event.stage === 'formatting' ? 'formatting' : 'flashing';
    }
    if (state.screen === 'work') renderWork();
  });

  $('useLocal').addEventListener('click', async () => {
    const res = await window.flasher.pickImage();
    if (!res.ok) return;
    state.local = res;
    state.release = null;
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
