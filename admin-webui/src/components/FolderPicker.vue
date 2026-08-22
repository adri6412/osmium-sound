<script setup>
// Folder picker over sources_server.py's /api/local/browse (through
// webui_server's session-gated forwarder, see api.js) — the same widget that
// "add a local folder", "share a local folder" and "playlist folder" all
// need, instead of the three near-identical copies SourcesPanel.vue used to
// carry. Each instance keeps its own browse position, so opening one doesn't
// move another. Mirrors the kiosk's FolderPicker in
// src/components/SourcesManager.jsx.
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';

const props = defineProps({
  startAt: { type: String, default: '' },
  pickLabel: { type: String, required: true },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['pick', 'error']);
const { t } = useI18n();

const path = ref(props.startAt);
const parent = ref(null);
const dirs = ref([]);
const loading = ref(false);
const newName = ref('');

async function browse(next) {
  loading.value = true;
  const r = await api.localBrowse(next || '');
  if (r.ok) {
    dirs.value = r.data.dirs || [];
    parent.value = r.data.parent;
    path.value = r.data.path || '';
  } else {
    emit('error', (r.data && r.data.message) || t('common.error'));
  }
  loading.value = false;
}

function up() {
  if (parent.value === null || parent.value === undefined) return;
  browse(parent.value);
}

async function createHere() {
  const name = newName.value.trim();
  if (!name || !path.value) return;
  loading.value = true;
  const r = await api.localMkdir(path.value, name);
  if (r.ok) { newName.value = ''; await browse(r.data.path); }
  else emit('error', (r.data && r.data.message) || t('common.error'));
  loading.value = false;
}

onMounted(() => browse(props.startAt));
</script>

<template>
  <div class="card" style="margin: 8px 0;">
    <div class="row" style="justify-content: space-between; align-items: center;">
      <span class="muted">{{ path || '/' }}</span>
      <button class="secondary fit" :disabled="parent === null || parent === undefined" @click="up">
        {{ t('settings.sources.subpathUp') }}
      </button>
    </div>
    <p v-if="loading" class="sub" style="margin-top: 8px;">{{ t('common.loading') }}</p>
    <template v-else>
      <p v-if="!dirs.length" class="sub" style="margin-top: 8px;">{{ t('settings.sources.subpathNoSubfolders') }}</p>
      <div v-for="dir in dirs" :key="dir" class="net" style="cursor: pointer;" @click="browse(dir)">{{ dir }}</div>
    </template>
    <div class="row" style="margin-top: 10px;">
      <input v-model="newName" type="text" :placeholder="t('settings.sources.newFolderPlaceholder')" />
      <button class="secondary fit" :disabled="loading || !newName.trim() || !path" @click="createHere">
        {{ t('settings.sources.newFolderCreate') }}
      </button>
    </div>
    <button style="margin-top: 10px;" :disabled="busy || !path" @click="emit('pick', path)">{{ pickLabel }}</button>
  </div>
</template>
