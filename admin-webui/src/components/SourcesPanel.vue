<script setup>
// Native replacement for the old SourcesFrame.vue iframe (which loaded a
// standalone page from sources_server.py over a separate pairing-token
// flow). Talks directly to sources_server.py through webui_server's
// session-gated forwarders (/api/system/sources|usb|internal|apply — see
// webui_server.py), same trust model as the native Backup & restore section
// in Settings.vue. sources_server.py itself is unchanged; this mirrors the
// kiosk's src/components/SourcesManager.jsx + InternalDisks.jsx.
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const props = defineProps({ setupMode: { type: Boolean, default: false } });
const { t } = useI18n();

const msg = ref('');
const err = ref(false);
function say(m, isErr = false) {
  msg.value = m;
  err.value = isErr;
  if (m) setTimeout(() => { if (msg.value === m) msg.value = ''; }, 6000);
}

const busy = ref(false);
const applying = ref(false);
// "Simple" (default) shows active sources + USB devices needing attention +
// Apply. "Advanced" adds internal-disk adoption/formatting and manual
// local/SMB folder entry — same idea as the kiosk's Semplice/Avanzate
// toggle, using the .seg segmented-button pattern already used elsewhere in
// Settings.vue (e.g. the Lyrion internal/external picker).
const view = ref('simple');

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

async function removeSource(id) {
  await api.sourcesRemove(id);
  loadSources();
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
  if (r.ok) { loadUsb(); loadSources(); }
  busy.value = false;
}

// ── Add local folder (file-browser picker, mirrors Lyrion's own folder
//    picker instead of a free-text path box) / SMB share ─────────────────
const addLocalOpen = ref(false);   // collapsed by default; expand on demand
const addLocalPath = ref('');      // '' = showing the top-level roots list
const addLocalParent = ref(null);
const addLocalDirs = ref([]);
const addLocalBusy = ref(false);
const addLocalSamba = ref(false);  // also create a network-writable Samba share
const newFolderName = ref('');

function toggleAddLocal() {
  addLocalOpen.value = !addLocalOpen.value;
  if (addLocalOpen.value && !addLocalDirs.value.length) loadAddLocalBrowse();
}
async function loadAddLocalBrowse() {
  addLocalBusy.value = true;
  const r = await api.localBrowse(addLocalPath.value);
  if (r.ok) {
    addLocalDirs.value = r.data.dirs || [];
    addLocalParent.value = r.data.parent;
    addLocalPath.value = r.data.path || '';
  } else {
    say((r.data && r.data.message) || t('common.error'), true);
  }
  addLocalBusy.value = false;
}
function addLocalInto(dir) {
  addLocalPath.value = dir;
  loadAddLocalBrowse();
}
function addLocalUp() {
  if (addLocalParent.value === null || addLocalParent.value === undefined) return;
  addLocalPath.value = addLocalParent.value;
  loadAddLocalBrowse();
}
async function createFolderHere() {
  const name = newFolderName.value.trim();
  if (!name || !addLocalPath.value) return;
  addLocalBusy.value = true;
  const r = await api.localMkdir(addLocalPath.value, name);
  if (r.ok) { newFolderName.value = ''; addLocalPath.value = r.data.path; await loadAddLocalBrowse(); }
  else say((r.data && r.data.message) || t('common.error'), true);
  addLocalBusy.value = false;
}
async function addLocal() {
  if (!addLocalPath.value) return;
  busy.value = true;
  const r = await api.sourcesAddLocal(addLocalPath.value, addLocalSamba.value);
  say(r.ok ? t('settings.sources.added') : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { addLocalPath.value = ''; addLocalSamba.value = false; loadAddLocalBrowse(); loadSources(); }
  busy.value = false;
}

const smb = reactive({ server: '', share: '', username: '', password: '', rw: false });
async function addSmb() {
  if (!smb.server.trim() || !smb.share.trim()) return;
  busy.value = true;
  say(t('settings.sources.mounting'));
  const r = await api.sourcesAddSmb({ ...smb });
  say(r.ok ? t('settings.sources.mounted') : ((r.data && r.data.message) || t('common.error')), !r.ok);
  if (r.ok) { smb.server = ''; smb.share = ''; smb.username = ''; smb.password = ''; smb.rw = false; loadSources(); }
  busy.value = false;
}

// ── Apply & rescan ─────────────────────────────────────────────────────
async function apply() {
  if (props.setupMode) {
    // The setup wizard applies the final source list itself, once, right
    // before handing off to Lyrion's own setup wizard — mirrors the old
    // iframe's behaviour under ?setup=1.
    say(t('settings.sources.applied'));
    return;
  }
  applying.value = true;
  say(t('settings.sources.applying'));
  const r = await api.sourcesApply();
  say(r.ok ? ((r.data && r.data.message) || t('settings.sources.applied')) : ((r.data && r.data.message) || t('common.error')), !r.ok);
  applying.value = false;
}

// ── Internal disks (adopt existing / format) ──────────────────────────
const internalDisks = ref([]);
const smbCard = ref(null);

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  const gb = n / 1024 ** 3;
  if (gb <= 0) return '';
  return gb >= 1000 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB';
}
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
  if (r.ok) { loadInternal(); loadSources(); }
  busy.value = false;
}
async function removeInternal(sourceId) {
  if (!sourceId) return;
  await api.sourcesRemove(sourceId);
  say(t('settings.sources.internalRemoved'));
  loadInternal(); loadSources();
}
async function regenSmb() {
  await api.internalSmbRegenerate();
  loadSmbCard();
}
const hasAdoptedShares = computed(() => smbCard.value && Array.isArray(smbCard.value.shares) && smbCard.value.shares.length > 0);

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
  loadInternal(); loadSources(); loadSmbCard();
}

// ── Lifecycle: poll active sources + USB every 4s, internal disks every 5s
let sourcesTimer = null, usbTimer = null, internalTimer = null;
onMounted(() => {
  loadSources();
  loadUsb();
  loadInternal();
  loadSmbCard();
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
    <div class="seg" style="margin-bottom: 4px;">
      <button :class="{ active: view === 'simple' }" @click="view = 'simple'">{{ t('settings.sources.viewSimple') }}</button>
      <button :class="{ active: view === 'advanced' }" @click="view = 'advanced'">{{ t('settings.sources.viewAdvanced') }}</button>
    </div>

    <!-- Active sources -->
    <label style="margin-top: 16px; display: block;">{{ t('settings.sources.active') }}</label>
    <p v-if="!sources.length" class="sub">{{ t('settings.sources.none') }}</p>
    <template v-for="s in sources" :key="s.id">
    <div class="net between" style="align-items: center; gap: 16px; flex-wrap: wrap;">
      <div style="min-width: 260px;">
        <div>{{ s.name }} <span class="pill">{{ sourceTag(s) }}</span></div>
        <div class="muted" :style="{ color: sourceOk(s) ? '' : 'var(--danger)' }">{{ sourceSub(s) }}</div>
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

    <template v-if="view === 'advanced'">
      <!-- Internal disks -->
      <label style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1); display: block;">
        {{ t('settings.sources.internalTitle') }}
      </label>
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
          <div class="row">
            <template v-if="dk.adopted">
              <button class="danger fit" @click="removeInternal(dk.source_id)">{{ t('settings.sources.internalRemove') }}</button>
            </template>
            <template v-else>
              <button v-if="(dk.partitions || []).filter(p => p.fstype).length === 1"
                      class="secondary fit" :disabled="busy"
                      @click="adoptInternal((dk.partitions.filter(p => p.fstype))[0].path)">
                {{ t('settings.sources.internalAdopt') }}
              </button>
              <button class="danger fit" :disabled="busy" @click="openWizard(dk)">{{ t('settings.sources.internalFormat') }}</button>
            </template>
          </div>
        </div>
        <div v-if="!dk.adopted && (dk.partitions || []).filter(p => p.fstype).length > 1" style="padding-left: 14px;">
          <div v-for="p in dk.partitions.filter(p => p.fstype)" :key="p.path" class="net between">
            <span class="muted">{{ p.path }} · {{ p.fstype }}{{ p.label ? ' · ' + p.label : '' }}</span>
            <button class="secondary fit" :disabled="busy" @click="adoptInternal(p.path)">{{ t('settings.sources.internalUse') }}</button>
          </div>
        </div>
      </template>

      <div v-if="hasAdoptedShares" style="margin-top: 12px;">
        <template v-if="!smbCard.installed">
          <p class="sub" style="color: var(--danger);">{{ t('settings.sources.needOsUpdate') }}</p>
        </template>
        <template v-else>
          <label>{{ t('settings.sources.smbShareTitle') }}</label>
          <p class="muted">{{ t('settings.sources.smbShareHelp') }}</p>
          <div v-for="s in smbCard.shares" :key="s.source_id" class="muted">
            {{ '\\\\' + (smbCard.ip || smbCard.host) + '\\' + s.name }}
          </div>
          <div class="row" style="margin-top: 8px;">
            <span class="muted">{{ t('settings.sources.smbShareUser') }}: {{ smbCard.username }}</span>
            <span class="muted">{{ t('settings.sources.smbSharePass') }}: {{ smbCard.password }}</span>
          </div>
          <button class="secondary" style="margin-top: 8px;" @click="regenSmb">{{ t('settings.sources.smbRegenerate') }}</button>
        </template>
      </div>

      <!-- Add local folder — file-browser picker (mirrors Lyrion's own
           folder picker) instead of a free-text path box. -->
      <label style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1); display: block;">
        {{ t('settings.sources.addLocal') }}
      </label>
      <button class="secondary" @click="toggleAddLocal">
        {{ addLocalOpen ? t('common.close') : t('settings.sources.addLocal') }}
      </button>
      <div v-if="addLocalOpen" class="card" style="margin: 8px 0;">
        <div class="row" style="justify-content: space-between; align-items: center;">
          <span class="muted">{{ addLocalPath || '/' }}</span>
          <button class="secondary fit" :disabled="addLocalParent === null || addLocalParent === undefined" @click="addLocalUp">
            {{ t('settings.sources.subpathUp') }}
          </button>
        </div>
        <p v-if="addLocalBusy" class="sub" style="margin-top: 8px;">{{ t('common.loading') }}</p>
        <template v-else>
          <p v-if="!addLocalDirs.length" class="sub" style="margin-top: 8px;">{{ t('settings.sources.subpathNoSubfolders') }}</p>
          <div v-for="dir in addLocalDirs" :key="dir" class="net" style="cursor: pointer;" @click="addLocalInto(dir)">
            {{ dir }}
          </div>
        </template>
        <div class="row" style="margin-top: 10px;">
          <input v-model="newFolderName" type="text" :placeholder="t('settings.sources.newFolderPlaceholder')" />
          <button class="secondary fit" :disabled="addLocalBusy || !newFolderName.trim() || !addLocalPath" @click="createFolderHere">
            {{ t('settings.sources.newFolderCreate') }}
          </button>
        </div>
        <label class="row" style="align-items: center; gap: 8px; margin-top: 12px; cursor: pointer;">
          <input type="checkbox" v-model="addLocalSamba" style="width: auto;" />
          <span class="muted">{{ t('settings.sources.localSambaHint') }}</span>
        </label>
        <button style="margin-top: 10px;" :disabled="busy || !addLocalPath" @click="addLocal">
          {{ t('settings.sources.useThisFolder') }}
        </button>
      </div>

      <!-- Add network folder (SMB) -->
      <label style="margin-top: 18px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1); display: block;">
        {{ t('settings.sources.addSmb') }}
      </label>
      <div class="row">
        <div style="flex: 1;">
          <label>{{ t('settings.sources.server') }}</label>
          <input v-model="smb.server" type="text" placeholder="192.168.0.20" />
        </div>
        <div style="flex: 1;">
          <label>{{ t('settings.sources.share') }}</label>
          <input v-model="smb.share" type="text" :placeholder="t('settings.sources.sharePlaceholder')" />
        </div>
      </div>
      <div class="row">
        <div style="flex: 1;">
          <label>{{ t('settings.sources.user') }}</label>
          <input v-model="smb.username" type="text" :placeholder="t('settings.sources.userPlaceholder')" />
        </div>
        <div style="flex: 1;">
          <label>{{ t('settings.sources.pass') }}</label>
          <input v-model="smb.password" type="password" placeholder="••••••" />
        </div>
      </div>
      <div class="net between" style="margin-top: 8px;">
        <span class="muted">{{ t('settings.sources.smbRw') }}</span>
        <input v-model="smb.rw" type="checkbox" style="width: auto;" />
      </div>
      <button style="margin-top: 8px;" :disabled="busy" @click="addSmb">{{ t('settings.sources.mountAndAdd') }}</button>
    </template>

    <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>

    <button style="margin-top: 16px; width: 100%;" :disabled="applying" @click="apply">{{ t('settings.sources.apply') }}</button>
    <p class="muted" style="margin-top: 6px;">{{ t('settings.sources.applyHint') }}</p>

    <!-- Format wizard -->
    <div v-if="wizardDisk" class="overlay">
      <div class="card" style="width: 360px;">
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
