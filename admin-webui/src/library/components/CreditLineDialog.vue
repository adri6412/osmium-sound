<script setup>
// One credit line: its group, its role, the instrument or voice (or a
// qualifier such as "assistant"), the words on the sleeve — and, when adding
// a credit, who and on which tracks. Used for "Add a credit", for changing an
// added one, and (without people and tracks) for changing the role of a line
// MusicBrainz gave.
import { ref, computed, watch } from 'vue';
import { useI18n } from '../../i18n';
import Icon from '../../components/Icon.vue';
import Modal from './Modal.vue';
import PersonPicker from './PersonPicker.vue';
import {
  GROUP_ORDER, ROLE_GROUPS, PER_ATTR_ROLES, groupLabel, roleName, roleLabel, attrSuggestions, attrSuggestionLabel, groupOfRole,
} from '../meta.js';

const props = defineProps({
  mode: { type: String, default: 'add' },           // 'add' | 'entry'
  initial: { type: Object, default: null },         // {group, role, attr, credit, people, tracks}
  // the album's tracks for "only on some tracks": [{disc, n, title}]
  albumTracks: { type: Array, default: () => [] },
  discs: { type: Number, default: 1 },
});
const emit = defineEmits(['close', 'save']);
const { t } = useI18n();

const init = props.initial || {};
const group = ref(init.group || 'performer');
const role = ref(init.role || (ROLE_GROUPS[init.group || 'performer'] || [])[0] || 'instrument');
const attr = ref(init.attr || '');
const credit = ref(init.credit || '');
const people = ref((init.people || []).map((p) => ({ name: p.name, artist_id: p.artist_id ?? null, mbid: p.mbid ?? null })));
const scope = ref(init.tracks && init.tracks.length ? 'some' : 'all');
const picked = ref(new Set((init.tracks || []).map((x) => x[0] + '.' + x[1])));
const choosing = ref(props.mode === 'add' && people.value.length === 0);

// The roles of the chosen group; a role already on the line from another
// group (MusicBrainz is not always tidy) stays selectable.
const roles = computed(() => {
  const list = (ROLE_GROUPS[group.value] || []).slice();
  if (role.value && !list.includes(role.value)) list.unshift(role.value);
  return list;
});
watch(group, (g) => {
  if (!(ROLE_GROUPS[g] || []).includes(role.value)) role.value = (ROLE_GROUPS[g] || [])[0] || '';
});
watch(role, (r) => {
  const g = groupOfRole(r);
  if (g !== 'other' && g !== group.value) group.value = g;
});
const attrHelp = computed(() => {
  if (role.value === 'instrument') return t('library.credits.line.attrInstrument');
  if (role.value === 'vocal') return t('library.credits.line.attrVocal');
  if (PER_ATTR_ROLES.includes(role.value)) return t('library.credits.line.attrArranger');
  return t('library.credits.line.attrOther');
});
const suggestions = computed(() => attrSuggestions(role.value));
const preview = computed(() => roleLabel({ role: role.value, attr: attr.value.trim().toLowerCase(), credit: credit.value.trim() }));

function addPerson(p) {
  const key = (x) => (x.mbid ? 'm' + x.mbid : x.artist_id ? 'a' + x.artist_id : 'n' + x.name.toLowerCase());
  if (!people.value.some((x) => key(x) === key(p))) people.value.push({ name: p.name, artist_id: p.artist_id ?? null, mbid: p.mbid ?? null });
  choosing.value = false;
}
function removePerson(i) {
  people.value.splice(i, 1);
}
function toggleTrack(tr) {
  const k = tr.disc + '.' + tr.n;
  const next = new Set(picked.value);
  if (next.has(k)) next.delete(k); else next.add(k);
  picked.value = next;
}

const valid = computed(() => {
  if (!role.value) return false;
  if (props.mode === 'add' && !people.value.length) return false;
  if (props.mode === 'add' && scope.value === 'some' && !picked.value.size) return false;
  return true;
});

function save() {
  // the device stores instruments in lower case, as MusicBrainz names them
  const line = { group: group.value, role: role.value, attr: attr.value.trim().toLowerCase(), credit: credit.value.trim() };
  if (props.mode === 'add') {
    line.people = people.value.map((p) => ({ name: p.name, artist_id: p.artist_id ?? null, mbid: p.mbid ?? null }));
    line.tracks = scope.value === 'all' ? null
      : [...picked.value].map((k) => k.split('.').map(Number)).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  }
  emit('save', line);
}
</script>

<template>
  <Modal :title="mode === 'entry' ? t('library.credits.line.changeTitle') : initial ? t('library.credits.line.editTitle') : t('library.credits.line.addTitle')" wide @close="emit('close')">
    <p class="sub" v-if="mode === 'entry'">{{ t('library.credits.line.changeHelp') }}</p>
    <div class="lb-form2">
      <div>
        <label for="cl-group">{{ t('library.credits.line.group') }}</label>
        <select id="cl-group" v-model="group">
          <option v-for="g in GROUP_ORDER" :key="g" :value="g">{{ groupLabel(g) }}</option>
        </select>
      </div>
      <div>
        <label for="cl-role">{{ t('library.credits.line.role') }}</label>
        <select id="cl-role" v-model="role">
          <option v-for="r in roles" :key="r" :value="r">{{ roleName(r) }}</option>
        </select>
      </div>
    </div>
    <label for="cl-attr">{{ attrHelp }}</label>
    <input id="cl-attr" v-model="attr" list="cl-attr-list" autocomplete="off" />
    <datalist id="cl-attr-list">
      <option v-for="s in suggestions" :key="s" :value="s">{{ attrSuggestionLabel(role, s) }}</option>
    </datalist>
    <label for="cl-credit">{{ t('library.credits.line.credit') }}</label>
    <input id="cl-credit" v-model="credit" :placeholder="t('library.credits.line.creditPlaceholder')" />
    <p class="muted lb-preview">{{ t('library.credits.line.preview') }} <strong class="silver">{{ preview }}</strong></p>

    <template v-if="mode === 'add'">
      <label>{{ t('library.credits.line.people') }}</label>
      <div class="lb-chips" v-if="people.length">
        <span class="lb-chip" v-for="(p, i) in people" :key="i">
          <Icon :name="p.artist_id ? 'library' : p.mbid ? 'globe' : 'user'" :size="14" />
          <span>{{ p.name }}</span>
          <button type="button" class="lb-chip-x" :aria-label="t('library.credits.line.removePerson')" @click="removePerson(i)"><Icon name="x" :size="13" /></button>
        </span>
      </div>
      <PersonPicker v-if="choosing" allow-plain @pick="addPerson" />
      <button v-else type="button" class="lb-link" @click="choosing = true"><Icon name="plus" :size="14" /> {{ t('library.credits.line.addPerson') }}</button>

      <label>{{ t('library.credits.line.where') }}</label>
      <div class="seg">
        <button type="button" :class="{ active: scope === 'all' }" @click="scope = 'all'">{{ t('library.credits.line.wholeAlbum') }}</button>
        <button type="button" :class="{ active: scope === 'some' }" :disabled="!albumTracks.length" @click="scope = 'some'">{{ t('library.credits.line.someTracks') }}</button>
      </div>
      <div class="lb-trackpick" v-if="scope === 'some'">
        <label class="lb-check" v-for="tr in albumTracks" :key="tr.disc + '.' + tr.n">
          <input type="checkbox" :checked="picked.has(tr.disc + '.' + tr.n)" @change="toggleTrack(tr)" />
          <span class="muted">{{ discs > 1 ? tr.disc + '.' + tr.n : tr.n }}</span>
          <span>{{ tr.title }}</span>
        </label>
      </div>
    </template>

    <template #foot>
      <button type="button" class="ghost fit" @click="emit('close')">{{ t('common.cancel') }}</button>
      <button type="button" class="fit" :disabled="!valid" @click="save">{{ mode === 'entry' ? t('library.credits.line.apply') : initial ? t('library.credits.line.apply') : t('library.credits.line.add') }}</button>
    </template>
  </Modal>
</template>
