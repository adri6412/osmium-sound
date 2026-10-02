<script setup>
// What this device can change in the files, said once at the top: nothing
// when it plays from another server's library. Reads /api/library/status
// through useLibraryStatus(), shared with the album page.
import { computed } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import { useLibraryStatus } from '../status.js';

const { t } = useI18n();
const { status } = useLibraryStatus();

const remote = computed(() => status.value && status.value.local === false);
const unavailable = computed(() => status.value && status.value.local !== false && status.value.available === false);
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
</template>
