<script setup>
// Native replacement for the old SourcesFrame.vue iframe (which loaded a
// standalone page from sources_server.py over a separate pairing-token
// flow). Talks directly to sources_server.py through webui_server's
// session-gated forwarders (/api/system/sources|usb|internal|apply — see
// webui_server.py), same trust model as the native Backup & restore section
// in Settings.vue. sources_server.py itself is unchanged; this mirrors the
// kiosk's src/components/SourcesManager.jsx + InternalDisks.jsx.
//
// Laid out as four bands — active sources / add source / playlist folder /
// shared folders — matching the kiosk screen one-for-one. There is no
// "Apply & rescan" button: sources_server.py pushes every edit into Lyrion's
// live mediadirs and rescans on its own (_lyrion_push_live()), without the
// service restart that would cut off whatever is playing.
import { ref, reactive, computed, onMounted, onUnmounted, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import FolderPicker from './FolderPicker.vue';
import { useRouter } from 'vue-router';

const { t } = useI18n();
const router = useRouter();

const msg = ref('');
const err = ref(false);
function say(m, isErr = false) {
  msg.value = m;
  err.value = isErr;
  if (m) setTimeout(() => { if (msg.value === m) msg.value = ''; }, 6000);
}

const busy = ref(false);

// One band open at a time; the two container bands ("add source", "shared
// folders") hold their own single-open sub-band.
const open = ref('');
const openAdd = ref('');     // 'smb' | 'internal' | 'local'
const openShare = ref('');   // 'local'
function toggle(k) { open.value = open.value === k ? '' : k; }
function toggleAdd(k) {
  const opening = openAdd.value !== k;
  openAdd.value = opening ? k : '';
  // Opening "network folder" starts the LAN scan straight away: the list is
  // the point of the redesign, and waiting for a button to start it would put
  // the empty state back where the four boxes used to be.
  if (k === 'smb') { wizReset(); if (opening) wizScan(); }
}
function toggleShare(k) { openShare.value = openShare.value === k ? '' : k; }

// ── Active sources + USB needing attention ───────────────────────────
const sources = ref([]);
const usb = ref([]);

async function loadSources() {
  const r = await api.sourcesList();
  if (r.ok) sources.value = r.data.sources || [];
}
async function loadUsb() {
  const r = await api.usbList();
  if (r.ok) usb.value = r.data.disks || [];
}

function sourceTag(s) {
  if (s.type === 'smb') return s.rw ? t('settings.sources.smbTag') + ' · RW' : t('settings.sources.smbTag');
  if (s.type === 'internal') return t('settings.sources.internalTag');
  if (s.type === 'usb') return t('settings.sources.usbTag');
  return t('settings.sources.localTag');
}
function sourceSub(s) {
  if (s.type === 'smb') return `//${s.server}/${s.share} → ${s.mountpoint}${s.subpath ? '/' + s.subpath : ''}`;
  if (s.type === 'internal' || s.type === 'usb') return s.mountpoint + (s.subpath ? '/' + s.subpath : '');
  return s.path;
}
function sourceOk(s) {
  return (s.type === 'smb' || s.type === 'internal' || s.type === 'usb') ? s.mounted : s.exists;
}

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  const gb = n / 1024 ** 3;
  if (gb <= 0) return '';
  return gb >= 1000 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB';
}
// Free space needs one decimal below 10 GB, where fmtSize()'s whole-GB
// rounding would report a nearly-full disk as "0 GB".
function fmtBytes(bytes) {
  const gb = Number(bytes) / 1024 ** 3;
  if (!Number.isFinite(gb) || gb <= 0) return '';
  if (gb >= 1000) return (gb / 1024).toFixed(1) + ' TB';
  return gb >= 10 ? Math.round(gb) + ' GB' : gb.toFixed(1) + ' GB';
}

// Every edit applies itself (see the file header), so a successful one just
// refreshes what's on screen.
function changed() { loadSources(); loadSmbCard(); }

async function removeSource(id) {
  await api.sourcesRemove(id);
  changed();
}
async function setSmbRw(id, rw) {
  busy.value = true;
  const r = await api.sourcesSetRw(id, rw);
  say(r.ok ? (r.data.message || t('settings.sources.mounted')) : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) loadSources();
  busy.value = false;
}

// ── Subfolder picker (smb/internal/usb only) ───────────────────────────
// Lets a source be narrowed to a subfolder of its mount directly from here,
// instead of needing Lyrion's own setup wizard for that — see
// sources_server.py's api_set_subpath()/api_browse_subpath().
const browsingId = ref(null);
const browsePath = ref('');
const browseDirs = ref([]);
const browseParent = ref(null);
const browseBusy = ref(false);

async function loadBrowse() {
  browseBusy.value = true;
  const r = await api.sourcesBrowse(browsingId.value, browsePath.value);
  if (r.ok) {
    browseDirs.value = r.data.dirs || [];
    browseParent.value = r.data.parent;
  } else {
    say((r.data && r.data.message) || t('common.error'), true);
    browsingId.value = null;
  }
  browseBusy.value = false;
}
function openBrowse(s) {
  browsingId.value = s.id;
  browsePath.value = s.subpath || '';
  loadBrowse();
}
function closeBrowse() {
  browsingId.value = null;
}
function browseInto(name) {
  browsePath.value = browsePath.value ? browsePath.value + '/' + name : name;
  loadBrowse();
}
function browseUp() {
  if (browseParent.value === null || browseParent.value === undefined) return;
  browsePath.value = browseParent.value;
  loadBrowse();
}
async function useBrowsePath(path) {
  busy.value = true;
  const r = await api.sourcesSetSubpath(browsingId.value, path);
  say(r.ok ? (r.data.message || t('settings.sources.subpathSaved')) : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { closeBrowse(); loadSources(); }
  busy.value = false;
}
async function retryUsb(device) {
  busy.value = true;
  say(t('settings.sources.internalAdopting'));
  const r = await api.usbAdopt(device);
  say(r.ok ? t('settings.sources.internalAdopted') : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { loadUsb(); changed(); }
  busy.value = false;
}

// ── Add source: local folder / SMB share / internal disk ───────────────
// `samba` also publishes the folder on the network — that is what the
// "share a local folder" entry under Shared folders passes.
async function addLocal(path, samba) {
  if (!path) return;
  busy.value = true;
  const r = await api.sourcesAddLocal(path, samba);
  say(r.ok ? t('settings.sources.added') : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) changed();
  busy.value = false;
}

// ── Guided "add a network folder" ─────────────────────────────────────
// Four empty boxes (server, share, user, password) are unusable by anyone who
// does not already know what an SMB share is. The appliance now looks for the
// file servers on the LAN itself and reads back what each one shares, so this
// is a list to pick from; typing it all in survives as the fallback, one
// field at a time. Same endpoints and same steps as the kiosk's own wizard.
const wiz = reactive({
  step: 0,               // 0 find a device, 1 pick a folder, 2 confirm
  manual: false,         // "I'll type it myself"
  host: '', name: '', share: '',
  username: '', password: '',
  rw: false,
  busy: false,
  err: '', detail: '', detailOpen: false,
  needsAuth: false,
  canList: true,         // false when the shares of this server cannot be read
  noClient: false,       // ...because this appliance has no smbclient at all
});
const scan = reactive({ state: '', progress: 0, hosts: [] });
const wizShares = ref([]);
let scanTimer = null;

function wizStopScan() {
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
}
function wizReset() {
  wizStopScan();
  Object.assign(wiz, { step: 0, manual: false, host: '', name: '', share: '',
                       username: '', password: '', rw: false, busy: false,
                       err: '', detail: '', detailOpen: false,
                       needsAuth: false, canList: true, noClient: false });
  Object.assign(scan, { state: '', progress: 0, hosts: [] });
  wizShares.value = [];
}
function wizFail(data, fallbackKey) {
  wiz.err = (data && data.message) || t(fallbackKey);
  wiz.detail = (data && data.detail) || '';
  wiz.detailOpen = false;
}
async function wizScan() {
  wiz.manual = false; wiz.err = ''; wiz.detail = '';
  Object.assign(scan, { state: 'running', progress: 0, hosts: [] });
  await api.smbDiscoverStart();
  await wizPoll();
  wizStopScan();
  scanTimer = setInterval(wizPoll, 900);
}
async function wizPoll() {
  const r = await api.smbDiscoverStatus();
  if (!r.ok) { wizStopScan(); return; }
  scan.state = r.data.state || '';
  scan.progress = Number(r.data.progress || 0);
  scan.hosts = r.data.hosts || [];
  // Without smbclient (a device that has not taken the new image yet) the
  // shares cannot be listed, so the flow falls back to typing the name.
  if (r.data.tools && r.data.tools.shares === false) { wiz.canList = false; wiz.noClient = true; }
  if (scan.state !== 'running') wizStopScan();
}
async function wizPickHost(host) {
  wizStopScan();
  wiz.host = host.ip; wiz.name = host.name || host.ip;
  wiz.share = ''; wizShares.value = []; wiz.needsAuth = false;
  wiz.err = ''; wiz.detail = ''; wiz.step = 1;
  if (wiz.canList) await wizLoadShares();
}
async function wizLoadShares() {
  wiz.busy = true; wiz.err = ''; wiz.detail = '';
  const r = await api.smbShares({ server: wiz.host, username: wiz.username, password: wiz.password });
  wiz.busy = false;
  if (!r.ok || !r.data || r.data.success === false) {
    wizFail(r.data, 'settings.sources.wizListFailed');
    // A wrong password keeps the owner on the step that asked for it; only a
    // real failure falls back to typing the folder name.
    if (r.data && r.data.code === 'msg.smbBadCredentials') wiz.needsAuth = true;
    else wiz.canList = false;
    return;
  }
  wiz.needsAuth = !!r.data.needs_auth;
  wizShares.value = r.data.shares || [];
}
async function wizPickShare(name) {
  wiz.share = name; wiz.err = ''; wiz.detail = ''; wiz.busy = true;
  const r = await api.smbTest({ server: wiz.host, share: name,
                                username: wiz.username, password: wiz.password });
  wiz.busy = false;
  if (r.ok && r.data && r.data.success !== false) { wiz.step = 2; return; }
  wizFail(r.data, 'settings.sources.wizOpenFailed');
  // A wrong password is fixed on the step that asked for it, not at the end
  // under a "mount failed" the owner cannot place.
  if (r.data && r.data.code === 'msg.smbBadCredentials') { wiz.needsAuth = true; wiz.step = 1; }
}
async function wizAdd() {
  if (!wiz.host || !wiz.share) return;
  wiz.busy = true; wiz.err = ''; wiz.detail = '';
  say(t('settings.sources.mounting'));
  // defer_activation: mount only, don't hand the share to Lyrion yet -- the
  // user still needs to pick "whole share" or a subfolder below, through the
  // same browse/subpath endpoints as "Pick a subfolder" on an existing
  // source (see sources_server.py's api_add_smb()/api_set_subpath()).
  const r = await api.sourcesAddSmb({
    server: wiz.host, share: wiz.share, username: wiz.username,
    password: wiz.password, rw: wiz.rw, defer_activation: true,
  });
  wiz.busy = false;
  if (!r.ok || (r.data && r.data.success === false)) {
    wizFail(r.data, 'common.error');
    say((r.data && r.data.message) || t('common.error'), true);
    return;
  }
  const id = r.data.id;
  wizReset();
  await loadSources();
  loadSmbCard();
  const added = sources.value.find((x) => x.id === id);
  if (added) { open.value = 'active'; openBrowse(added); }
  say(t('settings.sources.chooseFolderHint'));
}

onBeforeUnmount(wizStopScan);

// ── Playlist folder ───────────────────────────────────────────────────
// Where Lyrion saves playlists created from the player. The appliance
// provisions a working default on its own (ensure_playlistdir() in
// sources_server.py); this is the override — the last thing Lyrion's own
// setup wizard used to ask for, now that the wizard is skipped entirely.
const playlistdir = ref('');
const playlistdirDefault = ref('');
const pldOpen = ref(false);

async function loadPlaylistdir() {
  const r = await api.playlistdirGet();
  if (!r.ok) return;
  playlistdir.value = r.data.path || '';
  playlistdirDefault.value = r.data.default || '';
}
async function savePlaylistdir(path) {
  if (!path) return;
  busy.value = true;
  const r = await api.playlistdirSet(path);
  say(r.ok ? ((r.data && r.data.message) || t('settings.sources.playlistdirSaved'))
           : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { pldOpen.value = false; loadPlaylistdir(); }
  busy.value = false;
}

// ── Internal disks (adopt existing / format) ──────────────────────────
// Adopted disks already appear under "Active sources", so this list only
// offers what isn't in use yet; an adopted one stays visible, without
// buttons, so the full set of hardware is still legible.
const internalDisks = ref([]);
const smbCard = ref(null);

async function loadInternal() {
  const r = await api.internalDisks();
  if (r.ok) internalDisks.value = r.data.disks || [];
}
async function loadSmbCard() {
  const r = await api.internalSmb();
  if (r.ok) smbCard.value = r.data;
}
async function adoptInternal(device) {
  busy.value = true;
  say(t('settings.sources.internalAdopting'));
  const r = await api.internalAdopt(device);
  say(r.ok ? t('settings.sources.internalAdopted') : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { loadInternal(); changed(); }
  busy.value = false;
}
async function regenSmb() {
  await api.internalSmbRegenerate();
  loadSmbCard();
}
const shares = computed(() => (smbCard.value && smbCard.value.shares) || []);

// Address to hand out for the shares: the IP when we know it (works even
// where mDNS doesn't), with the .local name as the fallback that survives a
// DHCP change. Both are shown — the second one only as a hint.
const smbHost = computed(() => (smbCard.value && (smbCard.value.ip || smbCard.value.host)) || '');
const smbAltHost = computed(() => {
  const c = smbCard.value || {};
  return c.ip && c.host && c.ip !== c.host ? c.host : '';
});
function winPath(name, host) { return `\\\\${host || smbHost.value}\\${name}`; }
function macPath(name, host) { return `smb://${host || smbHost.value}/${name}`; }

// ── "How do I mount this?" popup (Windows / macOS) ────────────────────
const howtoShare = ref(null);      // share object, null = closed
const howtoOs = ref('win');        // 'win' | 'mac'

const howtoSteps = computed(() => {
  const s = howtoShare.value;
  if (!s) return [];
  const win = howtoOs.value === 'win';
  const vars = { path: win ? winPath(s.name) : macPath(s.name), name: s.name };
  const keys = win
    ? ['smbHowtoWin1', 'smbHowtoWin2', 'smbHowtoWin3']
    : ['smbHowtoMac1', 'smbHowtoMac2', 'smbHowtoMac3', 'smbHowtoMac4'];
  return keys.map((k) => t(`settings.sources.${k}`, vars));
});

// ── Format wizard (single instance — one disk at a time) ──────────────
const wizardDisk = ref(null);
const wizardStep = ref('choose'); // choose | confirm | progress | done | error
const wizardFs = ref('ext4');
const wizardLabel = ref('Musica');
const wizardTyped = ref('');
const wizardStatus = ref(null);
const wizardError = ref('');
let wizardPollTimer = null;

function openWizard(disk) {
  wizardDisk.value = disk;
  wizardStep.value = 'choose';
  wizardFs.value = 'ext4';
  wizardLabel.value = 'Musica';
  wizardTyped.value = '';
}
function closeWizard() {
  if (wizardPollTimer) { clearInterval(wizardPollTimer); wizardPollTimer = null; }
  wizardDisk.value = null;
}
const wizardCanFormat = computed(() => wizardTyped.value.trim() === wizardLabel.value.trim() && wizardLabel.value.trim().length > 0);
const wizardPct = computed(() => {
  const p = wizardStatus.value && typeof wizardStatus.value.progress === 'number' ? wizardStatus.value.progress : 0;
  return Math.max(0, Math.min(100, Math.round(p)));
});

async function startFormat() {
  wizardStep.value = 'progress';
  const r = await api.internalFormat({
    device: wizardDisk.value.path, fs: wizardFs.value, label: wizardLabel.value,
    confirm: wizardDisk.value.confirm,
  });
  if (!r.ok || (r.data && r.data.success === false)) {
    wizardError.value = (r.data && r.data.message) || t('common.error');
    wizardStep.value = 'error';
    return;
  }
  wizardPollTimer = setInterval(async () => {
    const s = await api.internalFormatStatus();
    if (!s.ok) return;
    wizardStatus.value = s.data;
    if (s.data.state === 'done') {
      clearInterval(wizardPollTimer); wizardPollTimer = null;
      wizardStep.value = 'done';
    } else if (s.data.state === 'error') {
      clearInterval(wizardPollTimer); wizardPollTimer = null;
      wizardError.value = s.data.message || t('common.error');
      wizardStep.value = 'error';
    }
  }, 2000);
}
function wizardDone() {
  closeWizard();
  loadInternal(); changed();
}

// ── Lifecycle: poll active sources + USB every 4s, internal disks every 5s
let sourcesTimer = null, usbTimer = null, internalTimer = null;
onMounted(() => {
  loadSources();
  loadUsb();
  loadInternal();
  loadSmbCard();
  loadPlaylistdir();
  sourcesTimer = setInterval(loadSources, 4000);
  usbTimer = setInterval(loadUsb, 4000);
  internalTimer = setInterval(loadInternal, 5000);
});
onUnmounted(() => {
  clearInterval(sourcesTimer);
  clearInterval(usbTimer);
  clearInterval(internalTimer);
  if (wizardPollTimer) clearInterval(wizardPollTimer);
});
</script>

<template>
  <div>
    <p class="muted">{{ t('settings.sources.autoApplyHint') }}</p>

    <!-- ── Active sources ─────────────────────────────────────────── -->
    <div class="acc" :class="{ open: open === 'active' }">
      <div class="net between" @click="toggle('active')">
        <span>
          <span style="display: block;">{{ t('settings.sources.active') }}</span>
          <span class="muted">{{ sources.length ? t('settings.sources.countSummary', { count: sources.length }) : t('settings.sources.none') }}</span>
        </span>
        <span class="chev">{{ open === 'active' ? '⌄' : '›' }}</span>
      </div>
      <div v-if="open === 'active'" class="acc-body">
        <p v-if="!sources.length" class="sub">{{ t('settings.sources.none') }}</p>
        <template v-for="s in sources" :key="s.id">
          <div class="net between" style="align-items: center; gap: 16px; flex-wrap: wrap;">
            <div style="min-width: 260px;">
              <div>{{ s.name }} <span class="pill">{{ sourceTag(s) }}</span></div>
              <div class="muted" :style="{ color: sourceOk(s) ? '' : 'var(--danger)' }">{{ sourceSub(s) }}</div>
              <div v-if="s.usage" class="muted" style="opacity: 0.75;">
                {{ t('settings.sources.freeOf', { free: fmtBytes(s.usage.free), total: fmtBytes(s.usage.total) }) }}
              </div>
              <div v-if="s.pending_activation" class="muted" style="color: var(--danger);">
                {{ t('settings.sources.pendingChoice') }}
              </div>
            </div>
            <div class="row" style="flex-wrap: wrap; justify-content: flex-end;">
              <button v-if="s.type === 'smb'" class="secondary fit" :disabled="busy" @click="setSmbRw(s.id, !s.rw)">
                {{ s.rw ? t('settings.sources.smbMakeRo') : t('settings.sources.smbMakeRw') }}
              </button>
              <button v-if="['smb', 'internal', 'usb'].includes(s.type)" class="secondary fit" :disabled="busy || !s.mounted"
                      @click="browsingId === s.id ? closeBrowse() : openBrowse(s)">
                {{ t('settings.sources.subpathPick') }}
              </button>
              <button class="danger fit" @click="removeSource(s.id)">{{ t('settings.sources.remove') }}</button>
            </div>
          </div>

          <!-- Inline subfolder browser for the source currently being narrowed -->
          <div v-if="browsingId === s.id" class="card" style="margin: 6px 0 12px;">
            <div class="row" style="justify-content: space-between; align-items: center;">
              <span class="muted">/{{ browsePath || '' }}</span>
              <button class="secondary fit" @click="closeBrowse">{{ t('common.back') }}</button>
            </div>
            <p v-if="browseBusy" class="sub">{{ t('common.loading') }}</p>
            <template v-else>
              <div class="row" style="gap: 8px; margin: 8px 0;">
                <button class="secondary fit" :disabled="browseParent === null || browseParent === undefined" @click="browseUp">
                  {{ t('settings.sources.subpathUp') }}
                </button>
                <button class="fit" :disabled="busy" @click="useBrowsePath(browsePath)">
                  {{ t('settings.sources.subpathUseHere') }}
                </button>
                <button class="secondary fit" :disabled="busy || !browsePath" @click="useBrowsePath('')">
                  {{ t('settings.sources.subpathUseRoot') }}
                </button>
              </div>
              <p v-if="!browseDirs.length" class="sub">{{ t('settings.sources.subpathNoSubfolders') }}</p>
              <div v-for="name in browseDirs" :key="name" class="net" style="cursor: pointer;" @click="browseInto(name)">
                {{ name }}
              </div>
            </template>
          </div>
        </template>

        <!-- USB devices needing attention — healthy drives auto-adopt on their
             own (sources_server.py's usb_sync()) and show up above instead. -->
        <template v-if="usb.length">
          <label style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1); display: block;">
            {{ t('settings.sources.usbAttention') }}
          </label>
          <div v-for="dk in usb" :key="dk.path" class="net between" style="align-items: flex-start;">
            <div>
              <div>{{ dk.label || 'USB' }} <span class="pill">USB{{ dk.fstype ? ' ' + dk.fstype : '' }}{{ dk.size ? ' · ' + dk.size : '' }}</span></div>
              <div class="muted" style="color: var(--danger);">{{ dk.needs_format ? t('settings.sources.usbNeedsFormat') : t('settings.sources.usbMountError') + ': ' + (dk.error || '') }}</div>
            </div>
            <button v-if="!dk.needs_format" class="secondary fit" :disabled="busy || !dk.path" @click="retryUsb(dk.path)">
              {{ t('settings.sources.usbRetry') }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- ── Add source ─────────────────────────────────────────────── -->
    <div class="acc" :class="{ open: open === 'add' }">
      <div class="net between" @click="toggle('add')">
        <span>
          <span style="display: block;">{{ t('settings.sources.addSource') }}</span>
          <span class="muted">{{ t('settings.sources.addSourceHint') }}</span>
        </span>
        <span class="chev">{{ open === 'add' ? '⌄' : '›' }}</span>
      </div>
      <div v-if="open === 'add'" class="acc-body">
        <!-- Network folder (SMB) -->
        <div class="acc" :class="{ open: openAdd === 'smb' }">
          <div class="net between" @click="toggleAdd('smb')">
            <span>{{ t('settings.sources.addSmb') }}</span>
            <span class="chev">{{ openAdd === 'smb' ? '⌄' : '›' }}</span>
          </div>
          <!-- Guided flow: find the device, pick the folder, confirm. -->
          <div v-if="openAdd === 'smb'" class="acc-body">
            <p class="sub">{{ t('settings.sources.wizIntro') }}</p>

            <!-- 1. which device -->
            <template v-if="wiz.step === 0">
              <template v-if="!wiz.manual">
                <p v-if="scan.state === 'running'" class="sub">
                  {{ t('settings.sources.wizSearching') }} — {{ scan.progress }}%
                </p>
                <div v-for="h in scan.hosts" :key="h.ip" class="net between" @click="wizPickHost(h)">
                  <span>
                    <span style="display: block;">{{ h.name || h.ip }}</span>
                    <span v-if="h.name" class="muted">{{ h.ip }}</span>
                  </span>
                  <span class="chev">›</span>
                </div>
                <p v-if="!scan.hosts.length && scan.state !== 'running'" class="sub">
                  {{ t('settings.sources.wizNothing') }}
                </p>
                <div class="row" style="margin-top: 10px;">
                  <button class="ghost" :disabled="scan.state === 'running'" @click="wizScan">
                    {{ t('settings.sources.wizSearchAgain') }}
                  </button>
                  <button class="ghost" @click="wiz.manual = true">{{ t('settings.sources.wizTypeIt') }}</button>
                </div>
              </template>
              <template v-else>
                <label>{{ t('settings.sources.wizAddress') }}</label>
                <input v-model="wiz.host" type="text" placeholder="192.168.0.20" />
                <p class="sub">{{ t('settings.sources.wizManualHint') }}</p>
                <div class="row">
                  <button :disabled="!wiz.host.trim()" @click="wizPickHost({ ip: wiz.host.trim(), name: '' })">
                    {{ t('settings.sources.wizContinue') }}
                  </button>
                  <button class="ghost" @click="wizScan">{{ t('settings.sources.wizSearchAgain') }}</button>
                </div>
              </template>
            </template>

            <!-- 2. which shared folder -->
            <template v-else-if="wiz.step === 1">
              <p class="sub">{{ t('settings.sources.wizOnDevice', { device: wiz.name || wiz.host }) }}</p>
              <template v-if="wiz.needsAuth || wiz.username">
                <p class="sub">{{ t('settings.sources.wizAuthHint') }}</p>
                <div class="row">
                  <div style="flex: 1;">
                    <label>{{ t('settings.sources.user') }}</label>
                    <input v-model="wiz.username" type="text" :placeholder="t('settings.sources.userPlaceholder')" />
                  </div>
                  <div style="flex: 1;">
                    <label>{{ t('settings.sources.pass') }}</label>
                    <input v-model="wiz.password" type="password" placeholder="••••••" />
                  </div>
                </div>
                <button style="margin-bottom: 10px;" :disabled="wiz.busy || !wiz.username" @click="wizLoadShares">
                  {{ t('settings.sources.wizSignIn') }}
                </button>
              </template>
              <p v-if="wiz.busy" class="sub">{{ t('settings.sources.wizLoadingShares') }}</p>
              <template v-else-if="!wiz.canList">
                <label>{{ t('settings.sources.wizShareLabel') }}</label>
                <input v-model="wiz.share" type="text" :placeholder="t('settings.sources.sharePlaceholder')" />
                <p class="sub">
                  <template v-if="wiz.noClient">{{ t('settings.sources.wizNoClientHint') }} </template>
                  {{ t('settings.sources.wizTypeShareHint') }}
                </p>
                <button :disabled="!wiz.share.trim()" @click="wiz.step = 2">{{ t('settings.sources.wizContinue') }}</button>
              </template>
              <template v-else>
                <div v-for="sh in wizShares" :key="sh.name" class="net between" @click="wizPickShare(sh.name)">
                  <span>
                    <span style="display: block;">{{ sh.name }}</span>
                    <span v-if="sh.comment" class="muted">{{ sh.comment }}</span>
                  </span>
                  <span class="chev">›</span>
                </div>
                <p v-if="!wizShares.length && !wiz.needsAuth" class="sub">{{ t('settings.sources.wizNoShares') }}</p>
                <div class="row" style="margin-top: 10px;">
                  <button v-if="!wiz.needsAuth && !wiz.username" class="ghost" @click="wiz.needsAuth = true">
                    {{ t('settings.sources.wizNeedPassword') }}
                  </button>
                  <button class="ghost" @click="wiz.canList = false">{{ t('settings.sources.wizTypeIt') }}</button>
                </div>
              </template>
            </template>

            <!-- 3. confirm -->
            <template v-else>
              <div class="pathlist">
                <span class="muted">{{ t('settings.sources.wizDevice') }}</span><span>{{ wiz.name || wiz.host }}</span>
                <span class="muted">{{ t('settings.sources.wizFolder') }}</span><span>{{ wiz.share }}</span>
                <template v-if="wiz.username">
                  <span class="muted">{{ t('settings.sources.user') }}</span><span>{{ wiz.username }}</span>
                </template>
              </div>
              <div class="net between" style="margin-top: 10px;">
                <span>
                  <span style="display: block;">{{ t('settings.sources.wizAllowWrite') }}</span>
                  <span class="muted">{{ t('settings.sources.wizWriteHint') }}</span>
                </span>
                <input v-model="wiz.rw" type="checkbox" style="width: auto;" />
              </div>
              <button style="margin-top: 10px;" :disabled="wiz.busy" @click="wizAdd">
                {{ t('settings.sources.wizAddNow') }}
              </button>
            </template>

            <!-- what went wrong, in words; the raw tool output stays reachable
                 but is never the only thing on screen -->
            <div v-if="wiz.err" class="msg err" style="margin-top: 10px;">
              {{ wiz.err }}
              <template v-if="wiz.detail">
                <button class="ghost fit" style="margin-left: 8px;" @click="wiz.detailOpen = !wiz.detailOpen">
                  {{ t(wiz.detailOpen ? 'settings.sources.wizHideDetail' : 'settings.sources.wizShowDetail') }}
                </button>
                <pre v-if="wiz.detailOpen" class="mono" style="white-space: pre-wrap; margin: 8px 0 0;">{{ wiz.detail }}</pre>
              </template>
            </div>
            <div v-if="wiz.step > 0" class="row" style="margin-top: 10px;">
              <button class="ghost fit" :disabled="wiz.busy" @click="wiz.step = wiz.step - 1; wiz.err = ''">
                {{ t('common.back') }}
              </button>
              <button class="ghost fit" @click="wizReset(); wizScan()">{{ t('settings.sources.wizStartOver') }}</button>
            </div>
          </div>
        </div>

        <!-- Internal disks -->
        <div class="acc" :class="{ open: openAdd === 'internal' }">
          <div class="net between" @click="toggleAdd('internal')">
            <span>{{ t('settings.sources.internalTitle') }}</span>
            <span class="chev">{{ openAdd === 'internal' ? '⌄' : '›' }}</span>
          </div>
          <div v-if="openAdd === 'internal'" class="acc-body">
            <p v-if="!internalDisks.length" class="sub">{{ t('settings.sources.internalNone') }}</p>
            <template v-for="dk in internalDisks" :key="dk.path">
              <div class="net between" style="align-items: flex-start;">
                <div>
                  <div>
                    {{ dk.model || dk.path }}
                    <span class="pill">{{ fmtSize(dk.size) }}</span>
                    <span v-if="dk.adopted" class="pill gold">{{ t('settings.sources.internalAdoptedBadge') }}</span>
                    <span v-else-if="dk.has_data" class="pill">{{ t('settings.sources.internalHasData') }}</span>
                  </div>
                  <div class="muted">{{ dk.path }}{{ dk.fstype ? ' · ' + dk.fstype : '' }}{{ dk.label ? ' · ' + dk.label : '' }}</div>
                </div>
                <div v-if="!dk.adopted" class="row">
                  <button v-if="(dk.partitions || []).filter(p => p.fstype).length === 1"
                          class="secondary fit" :disabled="busy"
                          @click="adoptInternal((dk.partitions.filter(p => p.fstype))[0].path)">
                    {{ t('settings.sources.internalAdopt') }}
                  </button>
                  <button class="danger fit" :disabled="busy" @click="openWizard(dk)">{{ t('settings.sources.internalFormat') }}</button>
                </div>
              </div>
              <div v-if="!dk.adopted && (dk.partitions || []).filter(p => p.fstype).length > 1" style="padding-left: 14px;">
                <div v-for="p in dk.partitions.filter(p => p.fstype)" :key="p.path" class="net between">
                  <span class="muted">{{ p.path }} · {{ p.fstype }}{{ p.label ? ' · ' + p.label : '' }}</span>
                  <button class="secondary fit" :disabled="busy" @click="adoptInternal(p.path)">{{ t('settings.sources.internalUse') }}</button>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- Local folder — file-browser picker (mirrors Lyrion's own folder
             picker) instead of a free-text path box. -->
        <div class="acc" :class="{ open: openAdd === 'local' }">
          <div class="net between" @click="toggleAdd('local')">
            <span>{{ t('settings.sources.addLocal') }}</span>
            <span class="chev">{{ openAdd === 'local' ? '⌄' : '›' }}</span>
          </div>
          <div v-if="openAdd === 'local'" class="acc-body">
            <FolderPicker
              :pick-label="t('settings.sources.useThisFolder')"
              :busy="busy"
              @pick="(p) => addLocal(p, false)"
              @error="(m) => say(m, true)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- ── Playlist folder ────────────────────────────────────────── -->
    <div class="acc" :class="{ open: open === 'playlist' }">
      <div class="net between" @click="toggle('playlist')">
        <span>
          <span style="display: block;">{{ t('settings.sources.playlistdirTitle') }}</span>
          <span class="muted" style="word-break: break-all;">{{ playlistdir || t('settings.sources.playlistdirUnset') }}</span>
        </span>
        <span class="chev">{{ open === 'playlist' ? '⌄' : '›' }}</span>
      </div>
      <div v-if="open === 'playlist'" class="acc-body">
        <p class="muted">{{ t('settings.sources.playlistdirHint') }}</p>
        <div class="net between" style="align-items: center; gap: 12px; flex-wrap: wrap;">
          <div class="muted" style="min-width: 220px; word-break: break-all;">
            {{ playlistdir || t('settings.sources.playlistdirUnset') }}
          </div>
          <div class="row" style="flex-wrap: wrap; justify-content: flex-end;">
            <button class="secondary fit" @click="pldOpen = !pldOpen">
              {{ pldOpen ? t('common.close') : t('settings.sources.playlistdirPick') }}
            </button>
            <button class="secondary fit"
                    :disabled="busy || !playlistdirDefault || playlistdir === playlistdirDefault"
                    @click="savePlaylistdir(playlistdirDefault)">
              {{ t('settings.sources.playlistdirDefault') }}
            </button>
          </div>
        </div>
        <!-- Start browsing from the folder in use, so "somewhere near here" is
             one click away rather than a walk down from /. -->
        <FolderPicker
          v-if="pldOpen"
          :start-at="playlistdir"
          :pick-label="t('settings.sources.playlistdirUse')"
          :busy="busy"
          @pick="savePlaylistdir"
          @error="(m) => say(m, true)"
        />
      </div>
    </div>

    <!-- ── Shared folders (what this player publishes on the network) ─ -->
    <div class="acc" :class="{ open: open === 'share' }">
      <div class="net between" @click="toggle('share')">
        <span>
          <span style="display: block;">{{ t('settings.sources.shareTitle') }}</span>
          <span class="muted">{{ shares.length ? t('settings.sources.shareCount', { count: shares.length }) : t('settings.sources.shareNone') }}</span>
        </span>
        <span class="chev">{{ open === 'share' ? '⌄' : '›' }}</span>
      </div>
      <div v-if="open === 'share'" class="acc-body">
        <p class="muted">{{ t('settings.sources.shareHint') }}</p>
        <p v-if="smbCard && !smbCard.installed" class="sub" style="color: var(--danger);">{{ t('settings.sources.needOsUpdate') }}</p>
        <template v-else-if="shares.length">
          <!-- The addresses are what people open this band for, so they are on
               screen straight away; Info only adds the step-by-step. -->
          <div v-for="s in shares" :key="s.source_id" class="item">
            <div class="between">
              <span>{{ s.name }}</span>
              <button class="secondary fit" @click="howtoShare = s">
                {{ t('settings.sources.smbInfo') }}
              </button>
            </div>
            <div class="pathlist">
              <span class="muted">Windows</span><span class="mono">{{ winPath(s.name) }}</span>
              <span class="muted">macOS</span><span class="mono">{{ macPath(s.name) }}</span>
            </div>
          </div>
          <p v-if="smbAltHost" class="muted" style="margin: 10px 0 0;">{{ t('settings.sources.smbAltHostHint', { host: smbAltHost }) }}</p>
          <div class="row" style="margin-top: 10px;">
            <span class="muted">{{ t('settings.sources.smbShareUser') }}: {{ smbCard.username }}</span>
            <span class="muted">{{ t('settings.sources.smbSharePass') }}: {{ smbCard.password }}</span>
          </div>
          <p class="muted" style="margin-top: 6px;">{{ t('settings.sources.smbRegenerateHint') }}</p>
          <button class="secondary" style="margin-top: 8px;" @click="regenSmb">{{ t('settings.sources.smbRegenerate') }}</button>
        </template>
        <p v-else class="sub">{{ t('settings.sources.shareNone') }}</p>

        <!-- Share a local folder: same picker as "add local folder", with the
             Samba flag set so music can be copied onto it from a PC. -->
        <div class="acc" :class="{ open: openShare === 'local' }">
          <div class="net between" @click="toggleShare('local')">
            <span>{{ t('settings.sources.shareLocal') }}</span>
            <span class="chev">{{ openShare === 'local' ? '⌄' : '›' }}</span>
          </div>
          <div v-if="openShare === 'local'" class="acc-body">
            <p class="muted">{{ t('settings.sources.localSambaHint') }}</p>
            <FolderPicker
              :pick-label="t('settings.sources.shareThisFolder')"
              :busy="busy"
              @pick="(p) => addLocal(p, true)"
              @error="(m) => say(m, true)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- File manager: tidying what is inside a folder is a different job from
         choosing which folders count as sources, so it gets its own page. -->
    <div class="acc">
      <div class="net between" @click="router.push('/files')">
        <span>
          <span style="display: block;">{{ t('files.open') }}</span>
          <span class="muted">{{ t('files.hint') }}</span>
        </span>
        <span class="chev">›</span>
      </div>
    </div>

    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>

    <!-- How to mount the share on a computer -->
    <div v-if="howtoShare" class="overlay" @click.self="howtoShare = null">
      <div class="card" style="width: 470px; max-width: calc(100vw - 32px); max-height: 84vh; overflow-y: auto;">
        <h3><span class="dot"></span>{{ t('settings.sources.smbHowtoTitle') }}</h3>
        <p class="sub">{{ t('settings.sources.smbHowtoIntro', { name: howtoShare.name }) }}</p>

        <div class="seg" style="margin-bottom: 12px;">
          <button :class="{ active: howtoOs === 'win' }" @click="howtoOs = 'win'">Windows</button>
          <button :class="{ active: howtoOs === 'mac' }" @click="howtoOs = 'mac'">macOS</button>
        </div>

        <div class="pathlist">
          <span class="muted">{{ t('settings.sources.smbHowtoPath') }}</span>
          <span class="mono">{{ howtoOs === 'win' ? winPath(howtoShare.name) : macPath(howtoShare.name) }}</span>
          <template v-if="smbAltHost">
            <span class="muted">{{ t('settings.sources.smbHowtoPathAlt') }}</span>
            <span class="mono">{{ howtoOs === 'win' ? winPath(howtoShare.name, smbAltHost) : macPath(howtoShare.name, smbAltHost) }}</span>
          </template>
          <span class="muted">{{ t('settings.sources.smbShareUser') }}</span><span class="mono">{{ smbCard.username }}</span>
          <span class="muted">{{ t('settings.sources.smbSharePass') }}</span><span class="mono">{{ smbCard.password }}</span>
        </div>

        <ol class="steps">
          <li v-for="(step, i) in howtoSteps" :key="i">{{ step }}</li>
        </ol>
        <p class="muted" style="margin: 10px 0 0;">
          {{ howtoOs === 'win' ? t('settings.sources.smbRegenerateHint') : t('settings.sources.smbHowtoMacTip') }}
        </p>
        <button style="width: 100%; margin-top: 16px;" @click="howtoShare = null">{{ t('common.close') }}</button>
      </div>
    </div>

    <!-- Format wizard -->
    <div v-if="wizardDisk" class="overlay">
      <div class="card" style="width: 360px; max-width: calc(100vw - 32px);">
        <template v-if="wizardStep === 'choose'">
          <h3>{{ t('settings.sources.wizardTitle') }}</h3>
          <p class="sub">{{ wizardDisk.model || wizardDisk.path }} · {{ fmtSize(wizardDisk.size) }}</p>
          <label>{{ t('settings.sources.fsLabel') }}</label>
          <div class="row">
            <button :class="{ secondary: wizardFs !== 'ext4' }" @click="wizardFs = 'ext4'" style="text-align: left;">
              <div>{{ t('settings.sources.fsExt4') }}</div>
              <div class="muted" style="font-size: 11px;">{{ t('settings.sources.fsExt4Hint') }}</div>
            </button>
            <button :class="{ secondary: wizardFs !== 'exfat' }" @click="wizardFs = 'exfat'" style="text-align: left;">
              <div>{{ t('settings.sources.fsExfat') }}</div>
              <div class="muted" style="font-size: 11px;">{{ t('settings.sources.fsExfatHint') }}</div>
            </button>
          </div>
          <label>{{ t('settings.sources.labelField') }}</label>
          <input v-model="wizardLabel" type="text" :maxlength="wizardFs === 'exfat' ? 11 : 16" />
          <div class="row" style="margin-top: 16px;">
            <button class="secondary" style="flex: 1;" @click="closeWizard">{{ t('common.cancel') }}</button>
            <button style="flex: 1;" :disabled="!wizardLabel.trim()" @click="wizardTyped = ''; wizardStep = 'confirm'">{{ t('common.next') }}</button>
          </div>
        </template>

        <template v-else-if="wizardStep === 'confirm'">
          <h3 style="color: var(--danger);">⚠ {{ t('settings.sources.warnTitle') }}</h3>
          <p class="sub">{{ t('settings.sources.warnBody', { model: wizardDisk.model || wizardDisk.path, size: fmtSize(wizardDisk.size), path: wizardDisk.path }) }}</p>
          <label>{{ t('settings.sources.typeToConfirm', { label: wizardLabel.trim() }) }}</label>
          <input v-model="wizardTyped" type="text" />
          <div class="row" style="margin-top: 16px;">
            <button class="secondary" style="flex: 1;" @click="wizardStep = 'choose'">{{ t('common.back') }}</button>
            <button class="danger" style="flex: 1;" :disabled="!wizardCanFormat" @click="startFormat">{{ t('settings.sources.formatNow') }}</button>
          </div>
        </template>

        <template v-else-if="wizardStep === 'progress'">
          <div style="text-align: center;">
            <div class="spinner"></div>
            <p class="sub">{{ (wizardStatus && wizardStatus.message) || t('settings.sources.phasePreparing') }}</p>
            <p class="muted">{{ wizardPct }}%</p>
            <p class="muted">{{ t('settings.sources.keepPowered') }}</p>
          </div>
        </template>

        <template v-else-if="wizardStep === 'done'">
          <div style="text-align: center;">
            <h3>{{ t('settings.sources.doneAdopted') }}</h3>
            <p class="sub">{{ t('settings.sources.doneHint') }}</p>
            <button style="width: 100%; margin-top: 12px;" @click="wizardDone">{{ t('common.close') }}</button>
          </div>
        </template>

        <template v-else-if="wizardStep === 'error'">
          <div style="text-align: center;">
            <h3 style="color: var(--danger);">{{ t('settings.sources.errorTitle') }}</h3>
            <p class="sub">{{ wizardError }}</p>
            <button style="width: 100%; margin-top: 12px;" @click="closeWizard">{{ t('common.close') }}</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
