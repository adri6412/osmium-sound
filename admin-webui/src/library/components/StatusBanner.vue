<script setup>
// What this device can change in the files, said once at the top: nothing
// when it plays from another server's library, and which formats are still
// waiting for a writer. Reads /api/library/status through useLibraryStatus(),
// shared with the album page.
import { computed } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import { useLibraryStatus } from '../status.js';

const props = defineProps({ compact: Boolean });
const { t } = useI18n();
const { status } = useLibraryStatus();

const remote = computed(() => status.value && status.value.local === false);
const unavailable = computed(() => status.value && status.value.local !== false && status.value.available === false);
// "MP3, M4A" — the formats with no writer yet, in capitals as people know them
const waiting = computed(() => {
  const w = (status.value && status.value.writers) || {};
  return Object.keys(w).filter((k) => !w[k]).map((k) => k.toUpperCase());
});
</script>

<template>
  <div class="lb-banner" v-if="remote">
    <Icon name="info" :size="18" />
    <span>{{ t('library.status.remote') }}</span>
  </div>
  <div class="lb-banner" v-else-if="unavailable">
    <Icon name="alert-triangle" :size="18" />
    <span>{{ t('library.status.unavailable') }}<template v-if="status.reason"> ({{ status.reason }})</template></span>
  </div>
  <div class="lb-banner soft" v-else-if="waiting.length && !compact">
    <Icon name="info" :size="18" />
    <span>{{ t('library.status.formatsLater', { formats: waiting.join(', ') }) }}</span>
  </div>
</template>
