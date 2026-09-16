<script setup>
// A dialog over the page: title, a body that scrolls on its own when it is
// taller than the screen, and a row of buttons that always stays in view.
import { onMounted, onBeforeUnmount } from 'vue';
import Icon from '../../components/Icon.vue';
import { useI18n } from '../../i18n';

const { t } = useI18n();

const props = defineProps({
  title: { type: String, default: '' },
  wide: Boolean,
  // a dialog that must not be dismissed by a stray tap (a save in progress)
  locked: Boolean,
});
const emit = defineEmits(['close']);

function onKey(e) {
  if (e.key === 'Escape' && !props.locked) emit('close');
}
onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));
</script>

<template>
  <div class="overlay lb-overlay" @click.self="!locked && emit('close')">
    <div class="lb-modal" :class="{ wide }" role="dialog" aria-modal="true">
      <div class="lb-modal-head">
        <h3>{{ title }}</h3>
        <button v-if="!locked" type="button" class="lb-ib" @click="emit('close')" :aria-label="t('common.close')">
          <Icon name="x" :size="18" />
        </button>
      </div>
      <div class="lb-modal-body"><slot /></div>
      <div class="lb-modal-foot" v-if="$slots.foot"><slot name="foot" /></div>
    </div>
  </div>
</template>
