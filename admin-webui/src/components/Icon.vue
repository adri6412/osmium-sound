<script setup>
// One lucide glyph, inline, taking its colour from the text around it.
//
// v-html is safe here by construction: `icons` is a frozen table of constants
// authored in icons.js, and an unknown name renders nothing rather than
// whatever was passed in — no value from the appliance can reach it.
import { computed } from 'vue';
import { icons } from '../icons.js';

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
});
const markup = computed(() => icons[props.name] || '');
</script>

<template>
  <svg
    class="ic" :width="size" :height="size" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
    v-html="markup"
  />
</template>
