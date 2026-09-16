<script setup>
// The values of one tag. Every tag is a list: most hold one value (a title),
// some hold several (two composers, "Name (instrument)" performers). One
// field per value, one under the other, and a way to add another — no
// separator character to learn, and a comma inside a name stays a comma.
import { computed } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  multi: { type: Boolean, default: true },
  placeholder: { type: String, default: '' },
  disabled: Boolean,
  numeric: Boolean,
  hint: { type: String, default: '' },
});
const emit = defineEmits(['update:modelValue']);
const { t } = useI18n();

// Always at least one field, empty when the tag has no value.
const rows = computed(() => (props.modelValue.length ? props.modelValue : ['']));

function setAt(i, v) {
  const next = rows.value.slice();
  next[i] = v;
  emit('update:modelValue', next.length === 1 && next[0] === '' ? [] : next);
}
function removeAt(i) {
  const next = rows.value.slice();
  next.splice(i, 1);
  emit('update:modelValue', next.length === 1 && next[0] === '' ? [] : next);
}
function add() {
  emit('update:modelValue', [...rows.value, '']);
}
</script>

<template>
  <div class="lb-values">
    <div class="lb-value" v-for="(v, i) in rows" :key="i">
      <input
        class="lb-in" :value="v" :disabled="disabled"
        :placeholder="i === 0 ? placeholder : ''"
        :inputmode="numeric ? 'numeric' : undefined"
        @input="setAt(i, $event.target.value)"
      />
      <button v-if="multi && rows.length > 1 && !disabled" type="button" class="lb-ib small"
              :title="t('library.tags.removeValue')" :aria-label="t('library.tags.removeValue')" @click="removeAt(i)">
        <Icon name="x" :size="15" />
      </button>
    </div>
    <div class="lb-values-foot" v-if="(multi && !disabled) || hint">
      <button v-if="multi && !disabled && rows[rows.length - 1] !== ''" type="button" class="lb-link" @click="add">
        <Icon name="plus" :size="14" /> {{ t('library.tags.addValue') }}
      </button>
      <span v-if="hint" class="lb-hint">{{ hint }}</span>
    </div>
  </div>
</template>
