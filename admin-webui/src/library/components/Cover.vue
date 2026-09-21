<script setup>
// An album cover through the admin's own origin (Lyrion is plain HTTP on
// :9000, the page may be HTTPS), with a quiet placeholder when there is none.
import { ref, watch } from 'vue';
import Icon from '../../components/Icon.vue';
import { lib } from '../libraryApi.js';

const props = defineProps({
  trackId: { type: [String, Number], default: '' },
  size: { type: Number, default: 300 },
});
const broken = ref(false);
watch(() => props.trackId, () => { broken.value = false; });
</script>

<template>
  <div class="lb-cover">
    <img v-if="trackId && !broken" :src="lib.coverUrl(trackId, size)" loading="lazy" alt="" @error="broken = true" />
    <Icon v-else name="disc" :size="34" />
  </div>
</template>
