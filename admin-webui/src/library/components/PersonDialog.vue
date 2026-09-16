<script setup>
// One person on one credit line: change how the name is written, point it
// at the right artist or MusicBrainz person, take it off the line. A new name
// or link — or no link at all — applies to the whole album (the same person on
// every line); taking someone off applies to this line only.
import { ref } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Modal from './Modal.vue';
import PersonPicker from './PersonPicker.vue';

const props = defineProps({
  person: { type: Object, required: true },    // {name, artist_id, mbid, orig, edited, removed, renamed, relinked}
  line: { type: String, default: '' },          // the line's label, "Tenor saxophone"
  lineHidden: Boolean,
});
const emit = defineEmits(['close', 'rename', 'link', 'unlink', 'remove', 'restore', 'reset']);
const { t } = useI18n();

const view = ref('menu');     // menu | rename | link
const name = ref(props.person.name);
</script>

<template>
  <Modal :title="person.name" @close="emit('close')">
    <p class="sub">
      {{ t('library.credits.person.onLine', { line }) }}
      <template v-if="person.orig && person.renamed"><br />{{ t('library.credits.person.originally', { name: person.orig.name }) }}</template>
    </p>
    <div class="lb-links">
      <span class="lb-linkstate" v-if="person.artist_id"><Icon name="library" :size="14" /> {{ t('library.credits.person.linkedLibrary') }}
        <button type="button" class="lb-unlink" @click="emit('unlink', 'library')"><Icon name="x" :size="12" /> {{ t('library.credits.person.unlink') }}</button></span>
      <span class="lb-linkstate" v-if="person.mbid"><Icon name="globe" :size="14" /> {{ t('library.credits.person.linkedMb') }}
        <a :href="'https://musicbrainz.org/artist/' + person.mbid" target="_blank" rel="noopener">musicbrainz.org <Icon name="external-link" :size="12" /></a>
        <button type="button" class="lb-unlink" @click="emit('unlink', 'musicbrainz')"><Icon name="x" :size="12" /> {{ t('library.credits.person.unlink') }}</button></span>
      <span class="lb-linkstate muted" v-if="!person.artist_id && !person.mbid">{{ t('library.credits.person.notLinked') }}</span>
    </div>

    <div v-if="view === 'menu'" class="lb-menu">
      <button type="button" class="lb-menu-i" @click="view = 'rename'">
        <Icon name="pencil" :size="17" /><span><strong>{{ t('library.credits.person.rename') }}</strong><span class="muted">{{ t('library.credits.person.renameHint') }}</span></span>
      </button>
      <button type="button" class="lb-menu-i" @click="view = 'link'">
        <Icon name="link" :size="17" /><span><strong>{{ t('library.credits.person.link') }}</strong><span class="muted">{{ t('library.credits.person.linkHint') }}</span></span>
      </button>
      <button v-if="!person.removed" type="button" class="lb-menu-i" :disabled="lineHidden" @click="emit('remove')">
        <Icon name="eye-off" :size="17" /><span><strong>{{ t('library.credits.person.remove') }}</strong><span class="muted">{{ t('library.credits.person.removeHint') }}</span></span>
      </button>
      <button v-else type="button" class="lb-menu-i" @click="emit('restore')">
        <Icon name="eye" :size="17" /><span><strong>{{ t('library.credits.person.restore') }}</strong></span>
      </button>
      <button v-if="person.edited" type="button" class="lb-menu-i" @click="emit('reset')">
        <Icon name="rotate-ccw" :size="17" /><span><strong>{{ t('library.credits.person.reset') }}</strong><span class="muted">{{ t('library.credits.person.resetHint') }}</span></span>
      </button>
    </div>

    <div v-else-if="view === 'rename'">
      <label for="pd-name">{{ t('library.credits.person.newName') }}</label>
      <input id="pd-name" v-model="name" @keydown.enter="name.trim() && emit('rename', name.trim())" />
      <p class="muted lb-note">{{ t('library.credits.person.renameHint') }}</p>
    </div>

    <div v-else-if="view === 'link'">
      <p class="muted lb-note">{{ t('library.credits.person.linkHelp') }}</p>
      <PersonPicker :initial="person.name" @pick="(p) => emit('link', p)" />
    </div>

    <template #foot>
      <template v-if="view === 'rename'">
        <button type="button" class="ghost fit" @click="view = 'menu'">{{ t('common.back') }}</button>
        <button type="button" class="fit" :disabled="!name.trim()" @click="emit('rename', name.trim())">{{ t('library.credits.line.apply') }}</button>
      </template>
      <template v-else-if="view === 'link'">
        <button type="button" class="ghost fit" @click="view = 'menu'">{{ t('common.back') }}</button>
      </template>
      <button v-else type="button" class="ghost fit" @click="emit('close')">{{ t('common.close') }}</button>
    </template>
  </Modal>
</template>
