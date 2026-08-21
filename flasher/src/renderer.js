'use strict';

/* Osmium Flasher — renderer. No Node access here; everything goes through the
   `flasher` bridge exposed by preload.js. */

// ── strings ────────────────────────────────────────────────────────────────
const STRINGS = {
  en: {
    'welcome.title': 'Prepare an Osmium Sound USB stick',
    'welcome.lead': 'This writes the installer image to a USB stick. Everything already on that stick will be erased.',
    'welcome.useLocal': 'Use an image already on this computer instead',
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
    'done.title': 'The USB stick is ready',
    'done.lead': 'Plug it into the mini PC, boot from it, and follow the installer on screen.',
    'error.title': 'It did not work',
    'error.support': 'If it keeps failing, write to support@osmiumsound.it with the detail above.',
    'btn.continue': 'Continue',
    'btn.back': 'Back',
    'btn.cancel': 'Cancel',
    'btn.write': 'Erase and write',
    'btn.close': 'Close',
    'btn.retry': 'Try again',
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
    'welcome.title': 'Prepara una chiavetta Osmium Sound',
    'welcome.lead': "Scrive l'immagine di installazione su una chiavetta USB. Tutto quello che c'è già sulla chiavetta verrà cancellato.",
    'welcome.useLocal': 'Usa invece un\'immagine già presente su questo computer',
    'welcome.loading': "Ricerca dell'immagine corrente…",
    'welcome.localPicked': 'Immagine locale — firma non verificata',
    'select.title': 'Scegli la chiavetta USB',
    'select.lead': 'Sono elencate solo le unità rimovibili. Il disco di sistema non compare mai.',
    'select.empty': 'Inserisci una chiavetta USB — comparirà qui automaticamente.',
    'select.readonly': 'protetta da scrittura',
    'select.toosmall': "troppo piccola per quest'immagine",
    'confirm.title': 'Ultimo controllo prima di cancellare',
    'confirm.warnTitle': 'Tutto il contenuto di questa unità verrà distrutto.',
    'confirm.warnBody': "L'immagine viene scritta direttamente sul dispositivo: le partizioni e i file esistenti non saranno più recuperabili.",
    'confirm.oversize': 'Questa unità supera i 256 GB — insolito per una chiavetta. Ho verificato che non è un disco esterno.',
    'work.downloading': "Download dell'immagine",
    'work.checking': "Controllo dell'immagine",
    'work.flashing': 'Scrittura sulla chiavetta',
    'work.verifying': 'Verifica di quanto scritto',
    'work.starting': 'In attesa dell\'autorizzazione…',
    'work.leadDownload': "L'immagine pesa circa 1 GB. Un download interrotto riprende da dove si era fermato.",
    'work.leadElevate': 'Il sistema chiederà la password: scrivere direttamente su un dispositivo richiede i permessi di amministratore.',
    'work.leadFlash': 'Non scollegare la chiavetta.',
    'done.title': 'La chiavetta è pronta',
    'done.lead': "Collegala al mini PC, avvialo da lì e segui l'installer sullo schermo.",
    'error.title': 'Non ha funzionato',
    'error.support': 'Se continua a fallire, scrivi a support@osmiumsound.it allegando il dettaglio qui sopra.',
    'btn.continue': 'Continua',
    'btn.back': 'Indietro',
    'btn.cancel': 'Annulla',
    'btn.write': 'Cancella e scrivi',
    'btn.close': 'Chiudi',
    'btn.retry': 'Riprova',
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
    'err.ESYSTEM': 'Quell\'unità sembra un disco di sistema ed è stata rifiutata.',
    'err.EREADONLY': 'La chiavetta è protetta da scrittura.',
    'err.ETOOSMALL': "La chiavetta è troppo piccola per quest'immagine.",
    'err.EWRITE': 'Scrittura fallita. Prova con un\'altra chiavetta o un\'altra porta USB.',
    'err.ECRASH': 'Il processo di scrittura si è interrotto in modo imprevisto.',
  },
};

let lang = 'en';
const t = (key) => (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
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
const state = {
  screen: 'welcome',
  release: null,
  local: null,          // locally picked image, bypasses the manifest
  imagePromise: null,   // download+verify running in the background
  imageResult: null,
  imageError: null,
  drives: [],
  selected: null,
  writing: false,
  phase: null,
  progress: null,
  error: null,
};

function show(screen) {
  state.screen = screen;
  document.querySelectorAll('.screen').forEach((el) => el.classList.remove('on'));
  $('screen' + screen[0].toUpperCase() + screen.slice(1)).classList.add('on');
  render();
}

// ── rendering ──────────────────────────────────────────────────────────────
function renderFooter() {
  const next = $('btnNext');
  const back = $('btnBack');
  const cancel = $('btnCancel');

  back.hidden = true;
  cancel.hidden = true;
  next.hidden = false;
  next.className = 'btn primary';

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
      next.textContent = t('btn.write');
      next.className = 'btn destroy';
      const needsAck = state.selected && state.selected.oversize;
      next.disabled = needsAck && !$('oversizeAck').checked;
      break;
    }
    case 'work':
      next.hidden = true;
      cancel.hidden = state.writing;      // a write in flight must not be torn off
      cancel.textContent = t('btn.cancel');
      break;
    case 'done':
      next.textContent = t('btn.close');
      next.disabled = false;
      break;
    case 'error':
      back.hidden = false;
      back.textContent = t('btn.close');
      next.textContent = t('btn.retry');
      next.disabled = false;
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
  $('useLocal').textContent = t('welcome.useLocal');
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
    else state.imageError = res;
    return res;
  });
}

async function runWrite() {
  show('work');
  state.phase = state.local ? 'starting' : 'downloading';
  state.progress = null;
  render();

  // Wait for the background download+verify that started when we left the
  // welcome screen; if the user brought their own file there is nothing to wait for.
  let img = state.local;
  if (!img) {
    const res = await state.imagePromise;
    if (!res.ok) return fail(res);
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
  show('done');
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
      state.phase = event.stage === 'verifying' ? 'verifying' : 'flashing';
      state.progress = event;
    } else if (event.type === 'stage') {
      state.phase = 'flashing';
    }
    if (state.screen === 'work') renderWork();
  });

  $('useLocal').addEventListener('click', async () => {
    const res = await window.flasher.pickImage();
    if (!res.ok) return;
    state.local = res;
    state.release = null;
    render();
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
        runWrite();
        break;
      case 'done':
        window.close();
        break;
      case 'error':
        state.error = null;
        state.imagePromise = null;
        state.imageResult = null;
        show('welcome');
        if (!state.local) loadManifest();
        break;
      default:
        break;
    }
  });

  $('btnBack').addEventListener('click', () => {
    if (state.screen === 'select') show('welcome');
    else if (state.screen === 'confirm') show('select');
    else if (state.screen === 'error') window.close();
  });

  $('btnCancel').addEventListener('click', async () => {
    await window.flasher.cancelImage();
    state.imagePromise = null;
    show('select');
  });

  await loadManifest();
});
