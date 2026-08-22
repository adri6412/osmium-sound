<script setup>
import { useI18n } from '../i18n';

// variant="compact" → small inline pill buttons (Login/Setup top bar)
// variant="list"    → full-width selectable rows (Settings → Lingua)
defineProps({ variant: { type: String, default: 'list' } });
const { lang, setLang, languages } = useI18n();
</script>

<template>
  <div v-if="variant === 'compact'" class="row" style="gap: 4px; justify-content: flex-end;">
    <button v-for="l in languages" :key="l.code" type="button"
            class="ghost fit" :class="{ active: l.code === lang }"
            style="padding: 6px 10px; font-size: 12px;"
            :title="l.name" @click="setLang(l.code)">
      {{ l.flag }} {{ l.code.toUpperCase() }}
    </button>
  </div>
  <div v-else>
    <div v-for="l in languages" :key="l.code" class="net between" @click="setLang(l.code)">
      <span>{{ l.flag }} {{ l.name }}</span>
      <span class="check" v-if="l.code === lang">✓</span>
    </div>
  </div>
</template>
