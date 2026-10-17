<script setup>
// A USB stick (web admin), like the kiosk's ImportWizard.qml: listen to it
// from there (sticks are taken into the library by themselves) or copy it
// into the appliance. Simple: where to, and "only what is missing" or
// "everything". Advanced: two panes FROM the stick TO the appliance. Then the
// copy, which carries on by itself when the window is closed.
import { ref, computed, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import PaneList from './PaneList.vue';
import FolderPicker from './FolderPicker.vue';
import { placeFor, gb } from '../sources-model.js';

const props = defineProps({ m: { type: Object, required: true }, stick: { type: Object, required: true } });
const emit = defineEmits(['close', 'job', 'back']);
const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);

const step = ref('what');        // what | adv | progress
const copyIt = ref(true);
const mode = ref('skip');
const dev = props.m.places.filter((p) => p.group === 'dev' && p.ok && p.root && p.rw);
const dest = ref((dev.find((p) => p.key !== 'sys') || dev[0] || { root: '' }).root);
const picking = ref(false);
const busy = ref(false); const err = ref('');
const job = ref(null); let timer = null;
const fromP = ref(null); const toP = ref(null);

const destPlace = computed(() => placeFor(props.m.places, dest.value));
function destName(p) {
  const pl = placeFor(props.m.places, p);
  if (!pl) return p;
  const rest = p.slice(pl.root.length).split('/').filter(Boolean);
  return [pl.group === 'dev' ? lt('Questo apparecchio', 'This appliance') : null, pl.name, ...rest].filter(Boolean).join(' › ');
}
const used = computed(() => (props.stick.usage ? props.stick.usage.total - props.stick.usage.free : 0));

async function start(op, paths, to, exists) {
  if (!paths.length || !to) return;
  busy.value = true; err.value = '';
  const r = await (op === 'move' ? api.filesMove(paths, to, exists) : api.filesCopy(paths, to, exists));
  busy.value = false;
  if (!r.ok || !r.data || r.data.success === false || !r.data.job) { err.value = (r.data && r.data.message) || lt('Non è riuscito', 'That did not work'); return; }
  step.value = 'progress'; job.value = { state: 'running', progress: 0 };
  emit('job', r.data.job);
  clearInterval(timer);
  timer = setInterval(async () => {
    const j = await api.filesJob(r.data.job);
    if (!j.ok) return;
    job.value = j.data;
    if (j.data.state === 'done' || j.data.state === 'error') clearInterval(timer);
  }, 800);
}
onBeforeUnmount(() => clearInterval(timer));
async function copyAll() {
  busy.value = true;
  const r = await api.filesList(props.stick.root);
  busy.value = false;
  if (!r.ok || !r.data || !r.data.entries) { err.value = lt('Non riesco a leggere la chiavetta', 'I cannot read the stick'); return; }
  start('copy', r.data.entries.map((e) => String(e.path)), dest.value, mode.value);
}
async function listen() {
  if (!props.stick.lib) await api.sourcesAddLocal(props.stick.root, false);
  emit('close');
}
const over = computed(() => job.value && (job.value.state === 'done' || job.value.state === 'error'));
</script>

<template>
  <div class="im-veil" @click.self="emit('close')">
    <div class="im" :class="{ big: step === 'adv' }">
      <div class="steps">
        <template v-for="(s, i) in [lt('Dove', 'Where'), lt('Cosa faccio', 'What to do'), lt('Fatto', 'Done')]" :key="s">
          <span :class="{ on: i === (step === 'progress' ? 2 : 1), past: i < (step === 'progress' ? 2 : 1) }"><i><Icon v-if="i < (step === 'progress' ? 2 : 1)" name="check" :size="12" /><template v-else>{{ i + 1 }}</template></i>{{ s }}</span>
          <em v-if="i < 2"></em>
        </template>
        <div v-if="step !== 'progress' && copyIt" class="seg">
          <button :class="{ on: step === 'what' }" @click="step = 'what'">{{ lt('Semplice', 'Simple') }}</button>
          <button :class="{ on: step === 'adv' }" @click="step = 'adv'"><Icon name="copy" :size="13" />{{ lt('Avanzate', 'Advanced') }}</button>
        </div>
        <button class="x" @click="emit('close')"><Icon name="x" :size="18" /></button>
      </div>

      <template v-if="step === 'what'">
        <h3>{{ stick.name }}{{ lt(': cosa ne faccio?', ': what do I do with it?') }}</h3>
        <p v-if="used">{{ lt('Contiene ', 'It holds ') }}{{ gb(used) }}{{ lt(". Puoi ascoltarla da lì o copiarla dentro l'apparecchio.", '. Listen to it from there, or copy it into the appliance.') }}</p>
        <div class="ways">
          <div class="way" :class="{ chosen: !copyIt }" @click="copyIt = false">
            <span class="ci"><Icon name="usb" :size="22" /></span>
            <div><b>{{ lt('Ascoltala dalla chiavetta', 'Listen from the stick') }}</b><span>{{ lt('Resta sulla chiavetta: si sente finché è collegata.', 'It stays on the stick: it plays while it is plugged in.') }}</span>
              <small>{{ stick.lib ? lt('È già nella libreria', 'Already in the library') : lt('La aggiungo alla libreria', 'I add it to the library') }}</small></div>
          </div>
          <div class="way" :class="{ chosen: copyIt }" @click="copyIt = true">
            <span class="ci"><Icon name="copy" :size="22" /></span>
            <div><b>{{ lt("Copiala nell'apparecchio", 'Copy it into the appliance') }}</b><span>{{ lt('Resta anche quando togli la chiavetta.', 'It stays when the stick goes.') }}</span>
              <small v-if="destPlace && destPlace.usage">{{ destPlace.name }}: {{ gb(destPlace.usage.free) }} {{ lt('liberi', 'free') }}</small></div>
            <span class="best">{{ lt('consigliata', 'recommended') }}</span>
          </div>
        </div>
        <template v-if="copyIt">
          <div class="lbl">{{ lt('Dove', 'Where') }}</div>
          <div class="where"><Icon name="folder" :size="17" class="g" /><span>{{ destName(dest) }}</span><button class="ghost2 sm" @click="picking = true">{{ lt('Cambia', 'Change') }}</button></div>
          <div class="lbl">{{ lt('Cosa', 'What') }}</div>
          <div class="radio" :class="{ chosen: mode === 'skip' }" @click="mode = 'skip'"><i></i><b>{{ lt('Solo quello che manca', 'Only what is missing') }}</b><span>{{ lt("quello che c'è già lo salto", 'what is already there is skipped') }}</span></div>
          <div class="radio" :class="{ chosen: mode === 'replace' }" @click="mode = 'replace'"><i></i><b>{{ lt('Tutto', 'Everything') }}</b><span>{{ lt("quello che c'è già lo sostituisco", 'what is already there is replaced') }}</span></div>
        </template>
        <p v-if="err" class="bad">{{ err }}</p>
        <div class="ft">
          <template v-if="copyIt"><Icon name="copy" :size="15" class="g" /><a href="#" @click.prevent="step = 'adv'">{{ lt('Avanzate: scegli tu cosa copiare e dove', 'Advanced: pick what to copy and where') }}</a></template>
          <span class="sp"></span>
          <button class="ghost2" @click="emit('back')"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button>
          <button class="go" :disabled="busy || (copyIt && !dest)" @click="copyIt ? copyAll() : listen()">
            <Icon :name="copyIt ? 'copy' : 'check'" :size="15" />{{ !copyIt ? (stick.lib ? lt('Va bene così', 'Fine as it is') : lt('Aggiungi alla libreria', 'Add to the library')) : lt('Copia', 'Copy') }}</button>
        </div>
      </template>

      <template v-else-if="step === 'adv'">
        <h3 class="adv">{{ lt('Scegli cosa copiare e dove', 'Pick what to copy and where') }}</h3>
        <div class="panes">
          <PaneList ref="fromP" :tag="lt('DA', 'FROM')" :start="stick.root" :places="m.places" active />
          <div class="mid"><span class="ar"><Icon name="chevron-right" :size="26" /></span><span>{{ lt('va in', 'goes to') }}</span></div>
          <PaneList ref="toP" :tag="lt('A', 'TO')" :start="dest" :top="destPlace ? destPlace.root : dest" :places="m.places" :selectable="false"
                    :mark="fromP ? fromP.sel.map((p) => p.split('/').pop()) : []" />
        </div>
        <p v-if="err" class="bad">{{ err }}</p>
        <div class="ft">
          <div class="exists"><small>{{ lt("Se c'è già", 'If it is already there') }}</small>
            <div class="seg2"><button v-for="o in [['skip', lt('Salta', 'Skip')], ['replace', lt('Sostituisci', 'Replace')], ['keep', lt('Tieni entrambi', 'Keep both')]]" :key="o[0]" :class="{ on: mode === o[0] }" @click="mode = o[0]">{{ o[1] }}</button></div></div>
          <span class="sp"></span>
          <button class="ghost2" @click="step = 'what'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button>
          <button class="ghost2" :disabled="busy || !fromP || !fromP.sel.length || !toP || !toP.writable" @click="start('move', fromP.sel, toP.path, mode)">{{ lt('Sposta', 'Move') }}</button>
          <button class="go" :disabled="busy || !fromP || !fromP.sel.length || !toP || !toP.writable" @click="start('copy', fromP.sel, toP.path, mode)"><Icon name="copy" :size="15" />{{ lt('Copia', 'Copy') }}</button>
        </div>
      </template>

      <template v-else>
        <h3>{{ job && job.state === 'error' ? lt('La copia si è fermata', 'The copy stopped') : over ? lt('Copia finita', 'Copy finished') : lt('Sto copiando la musica', 'Copying the music') }}</h3>
        <p :class="{ bad: job && job.state === 'error' }">{{ job && job.state === 'error' ? job.message
             : over ? lt('La libreria si aggiorna da sola: i brani compaiono in Musica fra poco. Ora puoi togliere la chiavetta.', 'The library updates by itself: the tracks show up in Music shortly. You can take the stick out now.')
             : lt('Puoi chiudere questa finestra: continuo da solo e i brani compaiono in Musica a copia finita. Non togliere la chiavetta finché non ho finito.', 'You can close this window: I carry on by myself and the tracks show up in Music when it is done. Do not take the stick out before I am finished.') }}</p>
        <div class="total">
          <div class="trow"><b>{{ (job && job.progress) || 0 }}%<template v-if="job && job.total"> · {{ gb(job.done || 0) }} {{ lt('di', 'of') }} {{ gb(job.total) }}</template></b>
            <span v-if="job && job.skipped">{{ lt("saltati perché c'erano già: ", 'skipped, already there: ') }}{{ job.skipped }}</span></div>
          <div class="fm-prog big"><i :style="{ width: ((job && job.progress) || 0) + '%' }"></i></div>
          <small v-if="job && job.current">{{ lt('Adesso: ', 'Now: ') }}{{ job.current }}</small>
        </div>
        <div class="ft"><span class="sp"></span><button class="go" @click="emit('close')">{{ over ? lt('Chiudi', 'Close') : lt('Chiudi, continua da solo', 'Close, carry on by yourself') }}</button></div>
      </template>
    </div>
    <div v-if="picking" class="im-veil" @click.self="picking = false">
      <div class="im">
        <FolderPicker :start-at="dest" :pick-label="lt('Copia qui', 'Copy here')" @pick="(p) => { dest = p; picking = false; }" />
        <button class="ghost2" style="margin-top: 10px" @click="picking = false">{{ lt('Annulla', 'Cancel') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.im-veil { position: fixed; inset: 0; background: rgba(0,0,0,0.72); display: flex; align-items: center; justify-content: center; z-index: 55; padding: 16px; }
.im { width: 860px; max-width: 100%; max-height: 94vh; overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 22px 26px; box-shadow: 0 25px 50px rgba(0,0,0,0.5); }
.im.big { width: 1120px; }
.go, .ghost2 { display: inline-flex; align-items: center; gap: 7px; border-radius: 10px; font-size: 14px; padding: 9px 15px; }
.go { background: var(--gold); color: #111; border: 0; font-weight: 700; }
.ghost2 { background: var(--light); color: var(--text); border: 0; }
.go:disabled, .ghost2:disabled { opacity: 0.4; }
.sm { padding: 6px 12px; font-size: 12.5px; }
.g { color: var(--gold); flex: 0 0 auto; }
.bad { color: #f0b4b4 !important; }
.sp { flex: 1 1 auto; }
.steps { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted); }
.steps span { display: inline-flex; align-items: center; gap: 7px; }
.steps i { width: 22px; height: 22px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); display: inline-flex; align-items: center; justify-content: center; font-style: normal; font-size: 11px; font-weight: 700; }
.steps .on { color: var(--text); font-weight: 700; }
.steps .on i { background: var(--gold); border-color: var(--gold); color: #111; }
.steps .past i { background: var(--gold-dim); border-color: rgba(212,175,55,0.5); color: var(--gold); }
.steps em { width: 26px; height: 1px; background: rgba(255,255,255,0.15); }
.seg { margin-left: auto; display: flex; background: var(--bg); border: 1px solid var(--border); border-radius: 18px; padding: 3px; }
.seg button, .seg2 button { display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 0; color: var(--silver); font-size: 13px; padding: 6px 16px; border-radius: 15px; }
.seg button.on, .seg2 button.on { background: var(--gold); color: #111; font-weight: 700; }
.seg2 { display: inline-flex; background: var(--bg); border: 1px solid var(--border); border-radius: 18px; padding: 3px; }
.x { margin-left: auto; background: transparent; border: 0; color: var(--muted); padding: 4px; }
.seg + .x { margin-left: 14px; }
.im h3 { font-size: 23px; margin: 16px 0 6px; font-weight: 700; display: block; }
.im h3.adv { font-size: 21px; margin-bottom: 12px; }
.im p { color: var(--muted); margin: 0 0 14px; font-size: 14px; line-height: 1.5; }
.ways { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.way { position: relative; display: flex; gap: 14px; padding: 16px; border-radius: 14px; background: var(--bg); border: 1px solid var(--border); cursor: pointer; }
.way.chosen { background: rgba(212,175,55,0.10); border: 1.5px solid var(--gold); }
.way .ci { flex: 0 0 auto; width: 46px; height: 46px; border-radius: 50%; background: var(--gold-dim); color: var(--gold); display: inline-flex; align-items: center; justify-content: center; }
.way.chosen .ci { background: var(--gold); color: #111; }
.way div { display: flex; flex-direction: column; gap: 4px; }
.way b { font-size: 15px; }
.way span { color: var(--muted); font-size: 12.5px; }
.way small { margin-top: 8px; color: var(--muted); font-size: 12.5px; }
.way.chosen small { color: var(--gold); }
.best { position: absolute; top: 14px; right: 14px; background: var(--gold); color: #111 !important; font-size: 11.5px !important; font-weight: 700; border-radius: 11px; padding: 3px 9px; }
.lbl { margin: 16px 0 7px; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); }
.where { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 14px; border-radius: 10px; background: var(--bg); border: 1px solid var(--border); font-size: 14px; }
.where span { flex: 1 1 auto; overflow-wrap: anywhere; }
.radio { display: flex; align-items: center; gap: 10px; padding: 11px 14px; border-radius: 10px; border: 1px solid var(--border); margin-bottom: 8px; font-size: 14px; cursor: pointer; flex-wrap: wrap; }
.radio.chosen { background: rgba(212,175,55,0.08); border-color: rgba(212,175,55,0.5); }
.radio i { width: 18px; height: 18px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.25); box-sizing: border-box; }
.radio.chosen i { border-color: var(--gold); background: radial-gradient(circle, var(--gold) 0 3.5px, transparent 4.5px); }
.radio span { color: var(--muted); font-size: 13px; }
.ft { display: flex; align-items: center; gap: 10px; border-top: 1px solid var(--border); margin-top: 16px; padding-top: 14px; font-size: 13.5px; flex-wrap: wrap; }
.ft a { color: var(--gold); }
.exists { display: flex; flex-direction: column; gap: 4px; }
.exists small { font-size: 10.5px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.panes { display: grid; grid-template-columns: 1fr 90px 1fr; gap: 10px; align-items: stretch; }
.mid { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--muted); font-size: 12.5px; }
.mid .ar { width: 52px; height: 52px; border-radius: 50%; background: var(--gold); color: #111; display: inline-flex; align-items: center; justify-content: center; }
.total { padding: 16px; border-radius: 12px; background: var(--bg); border: 1px solid var(--border); display: flex; flex-direction: column; gap: 10px; }
.trow { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.trow b { font-size: 16px; }
.trow span, .total small { color: var(--muted); font-size: 12.5px; overflow-wrap: anywhere; }
.fm-prog.big { height: 8px; border-radius: 4px; margin: 0; }
@media (max-width: 760px) { .ways { grid-template-columns: 1fr; } .panes { grid-template-columns: 1fr; } .mid { flex-direction: row; } }
</style>
