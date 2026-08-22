<script setup>
defineProps({ modelValue: Boolean, disabled: Boolean });
defineEmits(['update:modelValue']);
</script>

<template>
  <button type="button" class="toggle" :class="{ on: modelValue }" :disabled="disabled"
          @click="$emit('update:modelValue', !modelValue)">
    <span class="knob"></span>
  </button>
</template>
