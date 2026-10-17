<script setup>
// The File page: the two-pane file manager of Music sources (Commander.vue),
// the place asked for (?path=<its folder>, from the page of a place) on the
// left and another place on the right.
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from '../i18n';
import Commander from '../components/Commander.vue';
import { loadSources, setLang } from '../sources-model.js';

const { t, lang } = useI18n();
const route = useRoute();
const router = useRouter();
const places = ref([]);
const start = ref(String(route.query.path || ''));
onMounted(async () => {
  setLang((it, en) => (lang.value === 'it' ? it : en));
  const m = await loadSources();
  places.value = m.places;
});
</script>

<template>
  <a class="backlink" href="#" @click.prevent="router.push('/settings')">‹ {{ t('settings.backToSettings') }}</a>
  <h2 class="page">{{ t('files.title') }}</h2>
  <div class="card wide files-x">
    <Commander v-if="places.length" :start="start" :places="places" />
  </div>
</template>

<style>
.wrap:has(.files-x) { max-width: 1180px; }
@media (min-width: 900px) { .card.wide.files-x { width: auto; margin-left: 0; margin-right: 0; } }
</style>
