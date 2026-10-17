<script setup>
// Settings → Music sources, redrawn around the PLACES the music lives in
// (same model as the kiosk, sources-model.js): this appliance's system disk
// and second disk, USB sticks, network shares. A card per place says whether
// it works, how much room is left and what it is used for; it opens the page
// of its place, where every use is changed. "Add music" opens AddMusic.vue,
// a USB stick ImportMusic.vue. Only what is connected and mounted is listed.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import FolderPicker from './FolderPicker.vue';
import AddMusic from './AddMusic.vue';
import ImportMusic from './ImportMusic.vue';
import { loadSources, setLang, gb, under } from '../sources-model.js';

const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);
setLang(lt);
const router = useRouter();

const m = ref({ places: [], disks: [], usbBad: [], shares: [], smb: {}, loaded: false, albums: null, songs: null, libPaths: [], pldir: '', cd: {}, fmt: {} });
const view = ref('home');          // home | place
const placeKey = ref('');
const cur = computed(() => m.value.places.find((p) => p.key === placeKey.value) || null);
const msg = ref(''); const err = ref(false);
const showPw = ref(false);
const pick = ref(null);            // { start, label, fn }
const adding = ref(false);
const importing = ref(null);       // the stick's place
const jobId = ref(''); const job = ref(null);
let timer = null; let jobTimer = null;

async function load() {
  setLang(lt);
  m.value = await loadSources();
}
onMounted(() => { load(); timer = setInterval(load, 6000); });
onBeforeUnmount(() => { clearInterval(timer); clearInterval(jobTimer); });

function say(t, bad = false) { msg.value = t; err.value = bad; setTimeout(() => { if (msg.value === t) msg.value = ''; }, 6000); }
async function run(promise, ok) {
  const r = await promise;
  if (!r.ok || (r.data && r.data.success === false)) say((r.data && r.data.message) || lt('Non è riuscito', 'That did not work'), true);
  else if (ok) say(ok);
  load();
  return r;
}
const groups = computed(() => [['dev', lt('Questo apparecchio', 'This appliance')], ['usb', lt('Collegati via USB', 'Connected over USB')], ['net', lt('In rete', 'On the network')]]
  .map(([g, label]) => ({ g, label, items: m.value.places.filter((p) => p.group === g) })).filter((x) => x.items.length));
const bad = computed(() => m.value.places.filter((p) => !p.ok).length);
const newDisks = computed(() => m.value.disks.filter((d) => !d.adopted));
function usedPct(p) { return p.usage && p.usage.total ? Math.round(100 * (1 - p.usage.free / p.usage.total)) : 0; }
function statusLine(p) { return p.ok ? lt('Funziona', 'Working') + (p.rw ? lt(' · si può scrivere', ' · writable') : lt(' · sola lettura', ' · read only')) : p.error; }
function openPlace(p) { placeKey.value = p.key; view.value = 'place'; }

function choose(start, label, fn) { pick.value = { start, label, fn }; }
function picked(path) { const f = pick.value && pick.value.fn; pick.value = null; if (f) f(path); }
function addFolderHere(p, samba) {
  choose(p.root, samba ? lt('Condividi questa cartella', 'Share this folder') : lt('Aggiungi alla libreria', 'Add to the library'),
    (path) => run(api.sourcesAddLocal(path, !!samba), samba ? lt('Cartella condivisa', 'Folder shared') : lt('Aggiunta alla libreria', 'Added to the library')));
}
function onlyOne(p) {
  choose(p.root, lt('Usa solo questa cartella', 'Use only this folder'), (path) => {
    const rel = path === p.root ? '' : path.slice(p.root.length + 1);
    run(api.sourcesSetSubpath(p.src.id, rel), lt('Fatto', 'Done'));
  });
}
function playlistsHere(p) { choose(p.root, lt('Salva qui le playlist', 'Keep playlists here'), (path) => run(api.playlistdirSet(path), lt('Le playlist si salvano qui', 'Playlists are kept here'))); }
function ripHere(p) { choose(p.root, lt('Salva qui i CD rippati', 'Keep ripped CDs here'), (path) => run(api.cdSettingsSet({ target: path }), lt('I CD rippati finiscono qui', 'Ripped CDs go here'))); }
function removePlace(p) {
  if (!window.confirm(lt(`Togliere «${p.name}» dalla musica? I file restano dove sono.`, `Remove «${p.name}» from your music? The files stay where they are.`))) return;
  run(api.sourcesRemove(p.src.id)).then(() => { view.value = 'home'; });
}
function removeLocal(s) {
  if (!window.confirm(lt('Togliere questa cartella dalla libreria? I file restano dove sono.', 'Take this folder out of the library? The files stay where they are.'))) return;
  run(api.sourcesRemove(s.id));
}
function adopt(d) { run(api.internalAdopt(d.parts.length === 1 ? d.parts[0].path : d.path), lt('Preparo il disco…', 'Setting the disk up…')); }
function format(d) {
  const word = window.prompt(lt(`Preparare «${d.model || d.path}» da capo CANCELLA TUTTO quello che c'è sopra.\nPer confermare scrivi: ${d.confirm}`,
                                `Setting «${d.model || d.path}» up from scratch ERASES EVERYTHING on it.\nTo confirm, type: ${d.confirm}`), '');
  if (word !== d.confirm) return;
  run(api.internalFormat({ device: d.path, fs: 'ext4', label: 'Musica', confirm: d.confirm }), lt('Preparo il disco…', 'Setting the disk up…'));
}
function browse(p) { router.push({ path: '/files', query: { path: p.root } }); }
function follow(id) {
  jobId.value = id; clearInterval(jobTimer);
  jobTimer = setInterval(async () => {
    const r = await api.filesJob(id);
    if (!r.ok) { clearInterval(jobTimer); jobId.value = ''; return; }
    job.value = r.data;
    if (r.data.state === 'done' || r.data.state === 'error') { clearInterval(jobTimer); jobId.value = ''; load(); }
  }, 1000);
}
function openImport(p) { adding.value = false; importing.value = p; }
</script>

<template>
  <div class="ms">
    <!-- ── first page ─────────────────────────────────────────────── -->
    <template v-if="view === 'home'">
      <div class="ms-sum">
        <i class="bar" :class="{ warn: bad }"></i>
        <div class="tx">
          <b v-if="m.albums !== null">{{ lt(`${m.albums} album nella libreria`, `${m.albums} albums in the library`) }}<template v-if="m.songs !== null"> · {{ m.songs }} {{ lt('brani', 'tracks') }}</template></b>
          <b v-else>{{ m.loaded ? lt('La libreria', 'The library') : lt('Guardo dove sta la musica…', 'Looking where the music is…') }}</b>
          <span>{{ bad ? lt('Un posto non risponde: la sua musica torna quando si riaccende.', 'One place is not answering: its music comes back when it is on again.')
                       : lt(`Tutto funziona · la musica sta in ${m.places.length} ${m.places.length === 1 ? 'posto' : 'posti'}`, `All working · the music is in ${m.places.length} ${m.places.length === 1 ? 'place' : 'places'}`) }}</span>
        </div>
        <button class="go" @click="adding = true"><Icon name="plus" :size="16" />{{ lt('Aggiungi musica', 'Add music') }}</button>
      </div>
      <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
      <div v-if="jobId && job" class="ms-job">
        <Icon name="copy" :size="17" class="g" />
        <span>{{ lt('Sto copiando…', 'Copying…') }} {{ job.progress || 0 }}% <small>{{ job.current }}</small></span>
        <div class="fm-prog"><i :style="{ width: (job.progress || 0) + '%' }"></i></div>
      </div>

      <!-- what needs a hand -->
      <div v-for="d in newDisks" :key="d.path" class="ms-att">
        <Icon name="hard-drive" :size="20" class="w" />
        <div class="tx">
          <b>{{ lt("Un disco nuovo dentro l'apparecchio", 'A new disk inside the appliance') }} · {{ d.model || d.path }} · {{ gb(d.size) }}</b>
          <span>{{ d.hasData ? lt('Ha già dei file: puoi usarlo così, o prepararlo da capo (cancella tutto).', 'It already has files: use it as it is, or set it up from scratch (erases everything).') : lt('È vuoto: va preparato prima di usarlo.', 'It is empty: it needs setting up first.') }}</span>
          <div class="acts">
            <button v-if="d.parts.length" class="ghost2 sm" @click="adopt(d)">{{ lt('Usalo così', 'Use it as it is') }}</button>
            <button class="dang sm" @click="format(d)">{{ lt('Preparalo (cancella tutto)', 'Set it up (erases everything)') }}</button>
          </div>
        </div>
      </div>
      <div v-for="u in m.usbBad" :key="u.path || u.id" class="ms-att">
        <Icon name="usb" :size="20" class="w" />
        <div class="tx">
          <b>{{ u.label || u.model || 'USB' }}<template v-if="u.size"> · {{ u.size }}</template></b>
          <span>{{ u.needs_format ? lt('Non la so leggere: va formattata da un computer.', 'I cannot read it: format it on a computer.') : lt('Non si è montata: ', 'It did not mount: ') + (u.error || '') }}</span>
        </div>
        <button v-if="!u.needs_format" class="ghost2 sm" @click="run(api.usbAdopt(u.path || u.id), lt('Riprovo…', 'Trying again…'))">{{ lt('Riprova', 'Try again') }}</button>
      </div>
      <div v-if="m.fmt && m.fmt.state && !['idle', 'done'].includes(m.fmt.state)" class="msg">{{ m.fmt.message }}<template v-if="m.fmt.progress"> ({{ m.fmt.progress }}%)</template></div>

      <template v-for="g in groups" :key="g.g">
        <div class="ms-grp">{{ g.label }}</div>
        <div class="ms-grid">
          <div v-for="p in g.items" :key="p.key" class="ms-card" :class="{ bad: !p.ok }" @click="openPlace(p)">
            <div class="top">
              <span class="gl"><Icon :name="p.glyph" :size="20" /></span>
              <div class="nm"><b>{{ p.name }}</b><span>{{ p.kind }}</span></div>
              <Icon name="chevron-right" :size="16" class="chev" />
            </div>
            <div class="st"><i></i>{{ statusLine(p) }}</div>
            <template v-if="p.usage && p.usage.total">
              <div class="sp"><i :style="{ width: usedPct(p) + '%' }"></i></div>
              <div class="spt">{{ gb(p.usage.free) }} {{ lt('liberi su', 'free of') }} {{ gb(p.usage.total) }}</div>
            </template>
            <div class="roles">
              <span v-if="p.lib" class="role"><Icon name="music" :size="12" />{{ lt('Libreria', 'Library') }}</span>
              <span v-if="p.shared" class="role"><Icon name="share-2" :size="12" />{{ lt('Condivisa', 'Shared') }}</span>
              <span v-if="p.playlist" class="role"><Icon name="list-music" :size="12" />{{ lt('Playlist', 'Playlists') }}</span>
              <span v-if="p.rip" class="role"><Icon name="disc" :size="12" />{{ lt('Rip CD', 'CD rip') }}</span>
              <span v-if="!p.lib && !p.shared && !p.playlist && !p.rip" class="role off"><Icon name="music" :size="12" />{{ lt('Non ancora usato', 'Not used yet') }}</span>
            </div>
          </div>
        </div>
      </template>
      <div class="ms-legend">
        <span><Icon name="music" :size="13" /><b>{{ lt('Libreria', 'Library') }}</b> {{ lt('compare in Musica', 'shows in Music') }}</span>
        <span><Icon name="share-2" :size="13" /><b>{{ lt('Condivisa', 'Shared') }}</b> {{ lt('la vedi dal computer', 'you see it from a computer') }}</span>
        <span><Icon name="list-music" :size="13" /><b>{{ lt('Playlist', 'Playlists') }}</b> {{ lt('qui si salvano le playlist', 'playlists are kept here') }}</span>
        <span><Icon name="disc" :size="13" /><b>{{ lt('Rip CD', 'CD rip') }}</b> {{ lt('qui finiscono i CD copiati', 'ripped CDs go here') }}</span>
      </div>
    </template>

    <!-- ── the page of one place ──────────────────────────────────── -->
    <template v-else-if="cur">
      <a class="backlink" href="#" @click.prevent="view = 'home'">‹ {{ lt('La tua musica', 'Your music') }}</a>
      <div class="ms-head">
        <span class="gl" :class="{ bad: !cur.ok }"><Icon :name="cur.glyph" :size="22" /></span>
        <div><h3>{{ cur.name }}</h3><span class="muted">{{ cur.kind }}</span></div>
      </div>
      <div v-if="msg" class="msg" :class="{ err }">{{ msg }}</div>
      <div class="ms-box" :class="{ bad: !cur.ok }">
        <div class="st" :class="{ bad: !cur.ok }"><i></i>{{ statusLine(cur) }}</div>
        <template v-if="cur.usage && cur.usage.total">
          <div class="sp"><i :style="{ width: usedPct(cur) + '%' }"></i></div>
          <div class="spt">{{ gb(cur.usage.free) }} {{ lt('liberi su', 'free of') }} {{ gb(cur.usage.total) }}</div>
        </template>
        <button v-if="!cur.ok" class="ghost2 sm" @click="load"><Icon name="refresh-cw" :size="13" />{{ lt('Ricontrolla', 'Check again') }}</button>
      </div>

      <div class="ms-grp">{{ lt('Nella libreria', 'In the library') }}</div>
      <div v-if="cur.src" class="ms-row">
        <Icon name="music" :size="17" class="g" />
        <div class="tx"><b>{{ cur.src.subpath ? lt(`Solo la cartella «${cur.src.subpath}»`, `Only the folder «${cur.src.subpath}»`) : lt('Tutto il contenuto', 'All of it') }}</b><span>{{ cur.root }}<template v-if="cur.src.subpath">/{{ cur.src.subpath }}</template></span></div>
        <button class="ghost2 sm" :disabled="!cur.ok" @click="onlyOne(cur)">{{ lt('Solo una cartella…', 'Only one folder…') }}</button>
        <button v-if="cur.src.subpath" class="ghost2 sm" @click="run(api.sourcesSetSubpath(cur.src.id, ''), lt('Fatto', 'Done'))">{{ lt('Tutto', 'All of it') }}</button>
      </div>
      <div v-for="s in cur.locals" :key="s.id" class="ms-row" :class="{ bad: s.exists === false }">
        <Icon name="folder" :size="17" class="g" />
        <div class="tx"><b>{{ String(s.path).split('/').pop() }}</b><span><template v-if="s.exists === false">{{ lt('Non la trovo più · ', 'Not found any more · ') }}</template>{{ s.path }}<template v-if="s.samba"> · {{ lt('condivisa', 'shared') }}</template></span></div>
        <button class="dang sm" @click="removeLocal(s)">{{ lt('Togli', 'Remove') }}</button>
      </div>
      <p v-if="!cur.src && !cur.locals.length" class="muted">{{ lt('Niente di qui è nella libreria.', 'Nothing from here is in the library.') }}</p>
      <button v-if="!cur.src" class="ghost2" :disabled="!cur.ok" @click="addFolderHere(cur, false)"><Icon name="plus" :size="15" />{{ lt('Aggiungi una cartella di qui', 'Add a folder from here') }}</button>

      <div class="ms-grp">{{ lt('Usi', 'Uses') }}</div>
      <div class="ms-row" :class="{ on: cur.shared }">
        <span class="ug"><Icon name="share-2" :size="15" /></span>
        <div class="tx">
          <b>{{ cur.shared ? lt('Condivisa in rete', 'Shared on the network') : lt('Non condivisa', 'Not shared') }}</b>
          <span v-if="cur.shared">\\{{ m.smb.ip || m.smb.host }} · {{ lt('utente', 'user') }} {{ m.smb.username }} · password {{ showPw ? m.smb.password : '••••••' }}</span>
          <span v-else>{{ lt('Dal computer non la vedi.', 'A computer does not see it.') }}</span>
        </div>
        <button v-if="cur.shared" class="ghost2 sm" @click="showPw = !showPw">{{ showPw ? lt('Nascondi', 'Hide') : lt('Mostra password', 'Show password') }}</button>
        <button v-else-if="!cur.src" class="ghost2 sm" :disabled="!cur.ok" @click="addFolderHere(cur, true)">{{ lt('Condividi una cartella…', 'Share a folder…') }}</button>
      </div>
      <div class="ms-row" :class="{ on: cur.playlist }">
        <span class="ug"><Icon name="list-music" :size="15" /></span>
        <div class="tx"><b>{{ cur.playlist ? lt('Le playlist si salvano qui', 'Playlists are kept here') : lt('Le playlist si salvano altrove', 'Playlists are kept elsewhere') }}</b><span>{{ m.pldir }}</span></div>
        <button v-if="cur.ok && cur.rw" class="ghost2 sm" @click="playlistsHere(cur)">{{ cur.playlist ? lt('Cambia cartella', 'Change folder') : lt('Salvale qui', 'Keep them here') }}</button>
      </div>
      <div class="ms-row" :class="{ on: cur.rip }">
        <span class="ug"><Icon name="disc" :size="15" /></span>
        <div class="tx"><b>{{ cur.rip ? lt('I CD rippati finiscono qui', 'Ripped CDs go here') : lt('I CD rippati finiscono altrove', 'Ripped CDs go elsewhere') }}</b><span>{{ (m.cd && m.cd.target) || lt('cartella predefinita', 'default folder') }}</span></div>
        <button v-if="cur.ok && cur.rw" class="ghost2 sm" @click="ripHere(cur)">{{ cur.rip ? lt('Cambia cartella', 'Change folder') : lt('Salvali qui', 'Keep them here') }}</button>
      </div>
      <div v-if="cur.group === 'net'" class="ms-row" :class="{ on: cur.rw }">
        <span class="ug"><Icon name="pencil" :size="15" /></span>
        <div class="tx"><b>{{ cur.rw ? lt('Si può scrivere', 'Writable') : lt('Sola lettura', 'Read only') }}</b><span>{{ lt('Vale dal prossimo riavvio.', 'Takes effect at the next restart.') }}</span></div>
        <button class="ghost2 sm" @click="run(api.sourcesSetRw(cur.src.id, !cur.rw), lt('Vale dal prossimo riavvio', 'Takes effect at the next restart'))">{{ cur.rw ? lt('Rendi sola lettura', 'Make read only') : lt('Rendi scrivibile', 'Make writable') }}</button>
      </div>
      <div class="ms-foot">
        <button class="go" :disabled="!cur.ok" @click="browse(cur)"><Icon name="folder-open" :size="15" />{{ lt('Sfoglia i file', 'Browse the files') }}</button>
        <button v-if="cur.group === 'usb' && cur.ok" class="ghost2" @click="openImport(cur)"><Icon name="copy" :size="15" />{{ lt("Copia nell'apparecchio", 'Copy into the appliance') }}</button>
        <button v-if="cur.removable" class="dang" @click="removePlace(cur)"><Icon name="trash-2" :size="15" />{{ lt('Togli questo posto', 'Remove this place') }}</button>
      </div>
    </template>

    <!-- the folder picker, the File page's look -->
    <div v-if="pick" class="ms-veil" @click.self="pick = null">
      <div class="ms-modal">
        <FolderPicker :start-at="pick.start" :pick-label="pick.label" @pick="picked" />
        <button class="ghost2" style="margin-top: 10px" @click="pick = null">{{ lt('Annulla', 'Cancel') }}</button>
      </div>
    </div>
    <AddMusic v-if="adding" :m="m" @close="adding = false; load()" @import="openImport" @reload="load" />
    <ImportMusic v-if="importing" :m="m" :stick="importing" @close="importing = null; load()" @job="follow" @back="importing = null; adding = true" />
  </div>
</template>

<style scoped>
.ms { display: flex; flex-direction: column; gap: 12px; }
.go, .ghost2, .dang { display: inline-flex; align-items: center; gap: 7px; border-radius: 10px; font-size: 14px; padding: 9px 15px; }
.go { background: var(--gold); color: #111; border: 0; font-weight: 700; }
.ghost2 { background: var(--light); color: var(--text); border: 0; }
.dang { background: rgba(239,68,68,0.16); color: #f0b4b4; border: 0; }
.sm { padding: 6px 11px; font-size: 12.5px; border-radius: 8px; }
.go:disabled, .ghost2:disabled { opacity: 0.4; }
.g { color: var(--gold); }
.muted { color: var(--muted); font-size: 13px; }
.ms-sum { position: relative; display: flex; align-items: center; gap: 14px; padding: 14px 16px 14px 20px; border-radius: 14px; background: var(--panel); border: 1px solid var(--border); flex-wrap: wrap; }
.ms-sum .bar { position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 2px; background: #10b981; }
.ms-sum .bar.warn { background: #facc15; }
.ms-sum .tx { flex: 1 1 240px; display: flex; flex-direction: column; gap: 3px; }
.ms-sum .tx b { font-size: 16px; }
.ms-sum .tx span { color: var(--muted); font-size: 13px; }
.ms-job { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 12px; background: var(--panel); border: 1px solid rgba(212,175,55,0.4); font-size: 13px; flex-wrap: wrap; }
.ms-job small { color: var(--muted); }
.ms-job .fm-prog { flex: 1 1 160px; margin: 0; }
.ms-att { display: flex; align-items: flex-start; gap: 12px; padding: 14px; border-radius: 14px; background: var(--panel); border: 1px solid rgba(250,204,21,0.45); }
.ms-att .w { color: #facc15; flex: 0 0 auto; }
.ms-att .tx { flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
.ms-att .tx span { color: var(--muted); font-size: 12.5px; }
.ms-att .acts { display: flex; gap: 8px; margin-top: 6px; }
.ms-grp { font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase; color: var(--muted); font-weight: 700; margin: 6px 0 -4px 2px; }
.ms-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.ms-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 8px; cursor: pointer; }
.ms-card:hover { background: var(--light); }
.ms-card.bad { border-color: rgba(239,68,68,0.45); }
.top { display: flex; align-items: center; gap: 12px; }
.gl { width: 40px; height: 40px; border-radius: 10px; background: var(--gold-dim); color: var(--gold); display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.ms-card.bad .gl, .gl.bad { background: rgba(239,68,68,0.12); color: #f87171; }
.nm { flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.nm b { font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nm span { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chev { color: #666; }
.st { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 13px; color: #10b981; }
.st i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: 0 0 auto; }
.ms-card.bad .st, .st.bad { color: #f87171; }
.sp { height: 5px; border-radius: 3px; background: rgba(255,255,255,0.08); overflow: hidden; }
.sp i { display: block; height: 100%; background: var(--gold); }
.spt { color: var(--muted); font-size: 12px; margin-top: -3px; }
.roles { display: flex; flex-wrap: wrap; gap: 6px; }
.role { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 3px 9px; border-radius: 12px; color: var(--gold); border: 1px solid rgba(212,175,55,0.45); background: var(--gold-dim); }
.role.off { color: var(--muted); border-color: rgba(255,255,255,0.12); background: transparent; }
.ms-legend { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px 20px; padding: 12px 16px; border-radius: 14px; border: 1px dashed rgba(255,255,255,0.16); font-size: 12.5px; color: var(--silver); }
.ms-legend span { display: inline-flex; align-items: center; gap: 7px; }
.ms-legend :deep(.ic) { color: var(--gold); }
.ms-head { display: flex; align-items: center; gap: 14px; }
.ms .ms-head h3 { margin: 0; font-size: 20px; display: block; }
.ms-box { display: flex; flex-direction: column; gap: 8px; padding: 14px 16px; border-radius: 14px; background: var(--panel); border: 1px solid var(--border); }
.ms-box.bad { border-color: rgba(239,68,68,0.45); }
.ms-box .ghost2 { align-self: flex-start; }
.ms-row { display: flex; align-items: center; gap: 12px; padding: 11px 14px; border-radius: 12px; background: var(--panel); border: 1px solid var(--border); flex-wrap: wrap; }
.ms-row.on { border-color: rgba(212,175,55,0.35); }
.ms-row.bad { border-color: rgba(239,68,68,0.45); }
.ms-row .tx { flex: 1 1 220px; display: flex; flex-direction: column; gap: 2px; font-size: 14px; min-width: 0; }
.ms-row .tx span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.ug { width: 32px; height: 32px; border-radius: 8px; background: rgba(255,255,255,0.04); color: var(--muted); display: inline-flex; align-items: center; justify-content: center; }
.ms-row.on .ug { background: var(--gold-dim); color: var(--gold); }
.ms-foot { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.ms-veil { position: fixed; inset: 0; background: rgba(0,0,0,0.72); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 16px; }
.ms-modal { width: 820px; max-width: 100%; max-height: 92vh; overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 20px; }
</style>
