<script setup>
// "Add music" (web admin), the same wizard as the kiosk's AddMusicWizard.qml:
// where is the music — a USB stick, a computer or NAS, this appliance, or
// "I don't know, look for me" — with what was already found under the
// question. A USB stick goes on to ImportMusic.vue; a network share through
// device → shared folder → sign-in; a folder of this appliance is picked among
// the folders found on its disks (simple) or in the Explorer (advanced).
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import Icon from './Icon.vue';
import Explorer from './Explorer.vue';
import { under } from '../sources-model.js';

const props = defineProps({ m: { type: Object, required: true } });
const emit = defineEmits(['close', 'import', 'reload']);
const { lang } = useI18n();
const lt = (it, en) => (lang.value === 'it' ? it : en);

const step = ref('where');   // where | found | usb | net | netShares | netConfirm | folder | adv | done
const hosts = ref([]); const scanState = ref(''); const scanPct = ref(0); const canList = ref(true);
const host = ref(''); const hostName = ref(''); const share = ref(''); const user = ref(''); const pw = ref(''); const rw = ref(true);
const shares = ref([]); const needAuth = ref(false); const busy = ref(false); const err = ref('');
const cands = ref([]); const chosen = ref(''); const advPath = ref(''); const doneText = ref('');
const typedHost = ref(''); const typedShare = ref('');
let poll = null;

async function scan() {
  scanState.value = 'running'; scanPct.value = 0; hosts.value = [];
  await api.smbDiscoverStart();
  clearInterval(poll);
  poll = setInterval(async () => {
    const r = await api.smbDiscoverStatus();
    if (!r.ok || !r.data) return;
    scanState.value = String(r.data.state || ''); scanPct.value = Number(r.data.progress || 0);
    hosts.value = (r.data.hosts || []).map((h) => ({ ip: String(h.ip || ''), name: String(h.name || '') }));
    if (r.data.tools && r.data.tools.shares === false) canList.value = false;
    if (scanState.value !== 'running') clearInterval(poll);
  }, 900);
}
onMounted(scan);
onBeforeUnmount(() => clearInterval(poll));

const sticks = computed(() => props.m.places.filter((p) => p.group === 'usb' && p.ok));
const newDisks = computed(() => props.m.disks.filter((d) => !d.adopted));
function toUsb(p) {
  const s = p ? [p] : sticks.value;
  if (s.length === 1) { emit('import', s[0]); return; }
  step.value = 'usb';
}
// as soon as one stick appears while waiting, on to it
setInterval(() => { if (step.value === 'usb' && sticks.value.length === 1 && !props.m.usbBad.length) emit('import', sticks.value[0]); }, 1000);

function pickHost(ip, name) {
  clearInterval(poll); host.value = ip; hostName.value = name || ip; share.value = ''; shares.value = []; err.value = ''; needAuth.value = false;
  step.value = 'netShares';
  if (canList.value) loadShares();
}
async function loadShares() {
  busy.value = true; err.value = '';
  const r = await api.smbShares({ server: host.value, username: user.value, password: pw.value });
  busy.value = false;
  if (!r.ok || (r.data && r.data.success === false)) {
    if (r.data && r.data.code === 'msg.smbBadCredentials') { needAuth.value = true; err.value = user.value ? lt('Nome o password sbagliati', 'Wrong name or password') : ''; return; }
    err.value = (r.data && r.data.message) || lt("Non riesco a leggere l'elenco: scrivi il nome della cartella", 'I cannot read the list: type the folder name'); canList.value = false; return;
  }
  shares.value = (r.data.shares || []).map((x) => ({ name: String(x.name || ''), comment: String(x.comment || '') }));
  needAuth.value = !!r.data.needs_auth && !shares.value.length;
}
async function pickShare(name) {
  share.value = name; err.value = ''; busy.value = true;
  const r = await api.smbTest({ server: host.value, share: name, username: user.value, password: pw.value });
  busy.value = false;
  if (r.ok && r.data && r.data.success !== false) { step.value = 'netConfirm'; return; }
  if (r.data && r.data.code === 'msg.smbBadCredentials') { needAuth.value = true; err.value = user.value ? lt('Nome o password sbagliati', 'Wrong name or password') : lt('Questa cartella vuole nome e password', 'This folder wants a name and password'); return; }
  err.value = (r.data && r.data.message) || lt('Non riesco ad aprirla', 'I cannot open it');
}
async function addShare() {
  busy.value = true; err.value = '';
  const r = await api.sourcesAddSmb({ server: host.value, share: share.value, username: user.value, password: pw.value, rw: rw.value });
  busy.value = false;
  if (r.ok && r.data && r.data.success !== false) {
    doneText.value = lt(`«${share.value}» di ${hostName.value || host.value} è nella libreria: la musica compare in Musica man mano che la leggo.`, `«${share.value}» on ${hostName.value || host.value} is in the library: its music shows up in Music as I read it.`);
    step.value = 'done'; emit('reload'); return;
  }
  if (r.data && r.data.code === 'msg.smbBadCredentials') { step.value = 'netShares'; needAuth.value = true; err.value = lt('Nome o password sbagliati', 'Wrong name or password'); return; }
  err.value = (r.data && r.data.message) || lt('Non riesco ad aprirla', 'I cannot open it');
}

const inLib = (p) => props.m.libPaths.some((x) => under(p, x));
async function loadCands() {
  cands.value = []; chosen.value = '';
  const dev = props.m.places.filter((p) => p.group === 'dev' && p.ok && p.root);
  const out = [];
  for (const p of dev) {
    out.push({ name: p.key === 'sys' ? lt('Tutta la cartella della musica', 'The whole music folder') : lt('Tutto il disco', 'The whole disk'), place: p.name, path: p.root, inLib: inLib(p.root), whole: true });
    const r = await api.filesList(p.root);
    if (r.ok && r.data && r.data.entries) r.data.entries.filter((e) => e.dir).forEach((e) => out.push({ name: e.name, place: p.name, path: e.path, inLib: inLib(e.path), whole: false }));
  }
  out.sort((a, b) => (a.inLib - b.inLib) || (b.whole - a.whole));
  cands.value = out;
  const free = out.filter((c) => !c.inLib);
  chosen.value = free.length ? free[0].path : '';
}
function toFolder() { step.value = 'folder'; loadCands(); }
function toAdv() { step.value = 'adv'; }
const advStart = computed(() => (props.m.places[0] ? props.m.places[0].root : ''));
async function addFolder(path) {
  if (!path) return;
  busy.value = true; err.value = '';
  const r = await api.sourcesAddLocal(path, false);
  busy.value = false;
  if (r.ok && r.data && r.data.success !== false) { doneText.value = lt('La cartella è nella libreria: la musica compare in Musica man mano che la leggo.', 'The folder is in the library: its music shows up in Music as I read it.'); step.value = 'done'; emit('reload'); }
  else err.value = (r.data && r.data.message) || lt('Non è riuscito', 'That did not work');
}
const stepNo = computed(() => (['where', 'found'].includes(step.value) ? 0 : step.value === 'done' ? 2 : 1));
const choices = computed(() => [
  ['usb', lt('Su una chiavetta o disco USB', 'On a USB stick or disk'), lt("Collegala dietro all'apparecchio: la trovo da solo.", 'Plug it in at the back: I will find it.'), () => toUsb(null)],
  ['network', lt('Sul computer o sul NAS', 'On a computer or NAS'), lt('Una cartella condivisa in rete (Windows, Mac, NAS).', 'A folder shared on the network (Windows, Mac, NAS).'), () => { step.value = 'net'; }],
  ['speaker', lt('Dentro questo apparecchio', 'Inside this appliance'), lt('Sul disco di sistema o su un secondo disco montato dentro.', 'On the system disk or a second disk mounted inside.'), toFolder],
  ['sparkles', lt('Non lo so: cerca tu', "I don't know: look for me"), lt('Guardo USB, rete e dischi e ti mostro cosa c\'è.', 'I look at USB, network and disks and show you what is there.'), () => { step.value = 'found'; loadCands(); }, true],
]);
</script>

<template>
  <div class="am-veil" @click.self="emit('close')">
    <div class="am" :class="{ big: step === 'adv' }">
      <div class="steps">
        <template v-for="(s, i) in [lt('Dove', 'Where'), lt('Scegli', 'Choose'), lt('Fatto', 'Done')]" :key="s">
          <span :class="{ on: i === stepNo, past: i < stepNo }"><i><Icon v-if="i < stepNo" name="check" :size="12" /><template v-else>{{ i + 1 }}</template></i>{{ s }}</span>
          <em v-if="i < 2"></em>
        </template>
        <div v-if="step === 'folder' || step === 'adv'" class="seg">
          <button :class="{ on: step === 'folder' }" @click="toFolder">{{ lt('Semplice', 'Simple') }}</button>
          <button :class="{ on: step === 'adv' }" @click="toAdv"><Icon name="list" :size="13" />{{ lt('Avanzate', 'Advanced') }}</button>
        </div>
        <button class="x" @click="emit('close')"><Icon name="x" :size="18" /></button>
      </div>

      <!-- where -->
      <template v-if="step === 'where'">
        <h3>{{ lt('Dove si trova la tua musica?', 'Where is your music?') }}</h3>
        <p>{{ lt('Scegli la risposta che ti somiglia di più. Se non lo sai, nessun problema: cerco io.', 'Pick the answer closest to yours. If you do not know, no problem: I will look.') }}</p>
        <div class="ch">
          <div v-for="c in choices" :key="c[0]" class="c" :class="{ lead: c[4] }" @click="c[3]()">
            <span class="ci"><Icon :name="c[0]" :size="24" /></span>
            <div><b>{{ c[1] }}</b><span>{{ c[2] }}</span></div>
            <Icon name="chevron-right" :size="16" class="chev" />
          </div>
        </div>
        <div class="lbl"><Icon name="search" :size="12" />{{ scanState === 'running' ? lt('Sto cercando… ', 'Looking… ') + scanPct + '%' : lt('Trovato adesso, senza fare nulla', 'Found just now, by itself') }}</div>
        <div v-for="p in sticks.slice(0, 2)" :key="p.key" class="line"><Icon name="usb" :size="18" class="g" /><div><b>{{ p.name }}</b><span>{{ lt('collegata adesso', 'plugged in') }}</span></div><button class="go sm" @click="toUsb(p)">{{ lt('Cosa ne faccio?', 'What do I do with it?') }}</button></div>
        <div v-for="h in hosts.slice(0, Math.max(0, 2 - sticks.length))" :key="h.ip" class="line"><Icon name="network" :size="18" class="g" /><div><b>{{ h.name || h.ip }}</b><span>{{ h.name ? h.ip : lt('dispositivo in rete', 'network device') }}</span></div><button class="go sm" @click="pickHost(h.ip, h.name)">{{ lt('Aggiungi', 'Add') }}</button></div>
        <p v-if="!sticks.length && !hosts.length && scanState !== 'running'" class="muted">{{ lt('Per ora niente: collega una chiavetta o scegli qui sopra.', 'Nothing yet: plug in a stick or pick above.') }}</p>
        <div class="ft">
          <Icon name="list" :size="15" class="g" /><span class="muted">{{ lt('Sai già dove sta?', 'Know where it is?') }}</span>
          <a href="#" @click.prevent="toAdv">{{ lt('Avanzate: sfoglia tutte le cartelle', 'Advanced: browse every folder') }}</a>
          <span class="sp"></span><button class="ghost2" @click="emit('close')">{{ lt('Annulla', 'Cancel') }}</button>
        </div>
      </template>

      <!-- look for me -->
      <template v-else-if="step === 'found'">
        <h3>{{ lt('Ecco cosa ho trovato', 'Here is what I found') }}</h3>
        <p>{{ scanState === 'running' ? lt('Sto ancora guardando la rete… ', 'Still looking at the network… ') + scanPct + '%' : lt('Tocca quello che vuoi aggiungere.', 'Pick what you want to add.') }}</p>
        <div class="list">
          <div v-for="p in sticks" :key="p.key" class="line"><Icon name="usb" :size="18" class="g" /><div><b>{{ p.name }}</b><span>{{ lt('chiavetta USB collegata', 'USB stick plugged in') }}</span></div><button class="go sm" @click="toUsb(p)">{{ lt('Cosa ne faccio?', 'What do I do with it?') }}</button></div>
          <div v-for="d in newDisks" :key="d.path" class="line"><Icon name="hard-drive" :size="18" class="g" /><div><b>{{ lt('Disco nuovo dentro: ', 'New disk inside: ') }}{{ d.model || d.path }}</b><span>{{ lt('si prepara dalla pagina La tua musica', 'set it up from the Your music page') }}</span></div><button class="go sm" @click="emit('close')">{{ lt('Vai', 'Go') }}</button></div>
          <div v-for="h in hosts" :key="h.ip" class="line"><Icon name="network" :size="18" class="g" /><div><b>{{ h.name || h.ip }}</b><span>{{ h.name ? h.ip : lt('dispositivo in rete', 'network device') }}</span></div><button class="go sm" @click="pickHost(h.ip, h.name)">{{ lt('Aggiungi', 'Add') }}</button></div>
          <div v-for="c in cands.filter((x) => !x.inLib && !x.whole)" :key="c.path" class="line"><Icon name="folder" :size="18" class="g" /><div><b>{{ c.name }}</b><span>{{ c.place }}</span></div><button class="go sm" :disabled="busy" @click="addFolder(c.path)">{{ lt('Aggiungi', 'Add') }}</button></div>
        </div>
        <div class="ft2"><button class="ghost2" @click="step = 'where'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button><span class="sp"></span><button class="ghost2" @click="scan(); loadCands()"><Icon name="refresh-cw" :size="15" />{{ lt('Cerca ancora', 'Look again') }}</button></div>
      </template>

      <!-- usb: which, or plug one in -->
      <template v-else-if="step === 'usb'">
        <h3>{{ sticks.length ? lt('Quale chiavetta?', 'Which stick?') : lt('Collega la chiavetta', 'Plug the stick in') }}</h3>
        <p v-if="!sticks.length">{{ lt("Infilala in una presa USB dietro all'apparecchio: appena la vedo vado avanti da solo.", 'Put it in a USB port at the back: as soon as I see it I go on by myself.') }}</p>
        <div v-for="p in sticks" :key="p.key" class="line"><Icon name="usb" :size="18" class="g" /><div><b>{{ p.name }}</b></div><button class="go sm" @click="toUsb(p)">{{ lt('Questa', 'This one') }}</button></div>
        <div v-for="u in m.usbBad" :key="u.path || u.id" class="line"><Icon name="alert-triangle" :size="18" class="w" /><div><b>{{ u.label || u.model || 'USB' }}</b><span>{{ u.needs_format ? lt('Non la so leggere: va formattata da un computer', 'I cannot read it: format it on a computer') : u.error }}</span></div></div>
        <p v-if="!sticks.length" class="gold">{{ lt('Aspetto la chiavetta…', 'Waiting for the stick…') }}</p>
        <div class="ft2"><button class="ghost2" @click="step = 'where'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button></div>
      </template>

      <!-- network: which device -->
      <template v-else-if="step === 'net'">
        <h3>{{ lt('Su quale computer o NAS?', 'On which computer or NAS?') }}</h3>
        <p>{{ scanState === 'running' ? lt('Sto guardando la rete di casa… ', 'Looking at the home network… ') + scanPct + '%' : lt('Questi sono i dispositivi che condividono cartelle.', 'These are the devices sharing folders.') }}</p>
        <div class="list">
          <div v-for="h in hosts" :key="h.ip" class="line"><Icon name="network" :size="18" class="g" /><div><b>{{ h.name || h.ip }}</b><span>{{ h.name ? h.ip : '' }}</span></div><button class="go sm" @click="pickHost(h.ip, h.name)">{{ lt('Questo', 'This one') }}</button></div>
          <p v-if="!hosts.length && scanState !== 'running'" class="muted">{{ lt("Non ho trovato niente. È acceso? Puoi anche scrivere l'indirizzo.", 'I found nothing. Is it on? You can also type its address.') }}</p>
        </div>
        <div class="row2">
          <input v-model="typedHost" :placeholder="lt('Indirizzo (es. 192.168.1.20 o nas.local)', 'Address (e.g. 192.168.1.20 or nas.local)')" @keyup.enter="typedHost.trim() && pickHost(typedHost.trim().replace(/^\\\\|^\/\//, ''), '')" />
          <button class="ghost2" :disabled="!typedHost.trim()" @click="pickHost(typedHost.trim().replace(/^\\\\|^\/\//, ''), '')">{{ lt('Usa questo indirizzo', 'Use this address') }}</button>
        </div>
        <div class="ft2"><button class="ghost2" @click="step = 'where'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button><span class="sp"></span><button class="ghost2" :disabled="scanState === 'running'" @click="scan"><Icon name="refresh-cw" :size="15" />{{ lt('Cerca ancora', 'Look again') }}</button></div>
      </template>

      <!-- network: which folder (+ sign in when it wants one) -->
      <template v-else-if="step === 'netShares'">
        <h3>{{ lt('Quale cartella di ', 'Which folder on ') }}{{ hostName || host }}?</h3>
        <p :class="{ bad: err }">{{ busy ? lt("Chiedo l'elenco delle cartelle…", 'Asking for the list of folders…') : err || (user ? lt('Entrato come ', 'Signed in as ') + user : lt('Le cartelle che condivide in rete.', 'The folders it shares on the network.')) }}</p>
        <div v-if="needAuth" class="auth">
          <b>{{ lt('Questo dispositivo vuole nome utente e password', 'This device wants a user name and password') }}</b>
          <div class="row2"><input v-model="user" :placeholder="lt('Nome utente', 'User name')" autocomplete="off" /><input v-model="pw" type="password" :placeholder="lt('Password', 'Password')" autocomplete="off" @keyup.enter="share ? pickShare(share) : loadShares()" />
            <button class="go" :disabled="busy" @click="share ? pickShare(share) : loadShares()">{{ lt('Entra', 'Sign in') }}</button></div>
        </div>
        <div class="list">
          <div v-for="s in shares" :key="s.name" class="line"><Icon name="folder" :size="18" class="g" /><div><b>{{ s.name }}</b><span>{{ s.comment }}</span></div><button class="go sm" :disabled="busy" @click="pickShare(s.name)">{{ lt('Questa', 'This one') }}</button></div>
        </div>
        <div class="row2">
          <input v-model="typedShare" :placeholder="lt('…oppure scrivi il nome della cartella', '…or type the folder name')" @keyup.enter="typedShare.trim() && pickShare(typedShare.trim())" />
          <button class="ghost2" :disabled="!typedShare.trim() || busy" @click="pickShare(typedShare.trim())">{{ lt('Usa questa', 'Use this') }}</button>
        </div>
        <div class="ft2"><button class="ghost2" @click="step = 'net'; err = ''"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button><span class="sp"></span><button v-if="!needAuth" class="ghost2" @click="needAuth = true"><Icon name="lock" :size="14" />{{ lt('Nome e password', 'Name and password') }}</button></div>
      </template>

      <!-- network: confirm -->
      <template v-else-if="step === 'netConfirm'">
        <h3>{{ lt('Aggiungo questa cartella?', 'Add this folder?') }}</h3>
        <div class="line"><Icon name="network" :size="18" class="g" /><div><b>{{ share }}</b><span>//{{ host }}/{{ share }}<template v-if="user"> · {{ lt('utente', 'user') }} {{ user }}</template></span></div></div>
        <label class="chk" :class="{ on: rw }"><input v-model="rw" type="checkbox" /><div><b>{{ lt('Si può anche scrivere', 'Allow writing too') }}</b><span>{{ lt('Serve per salvarci i CD rippati, le playlist, o per sistemare le cartelle da qui.', 'Needed to keep ripped CDs or playlists there, or to tidy its folders from here.') }}</span></div></label>
        <p v-if="err" class="bad">{{ err }}</p>
        <p v-if="busy" class="gold">{{ lt('Collego la cartella…', 'Connecting the folder…') }}</p>
        <div class="ft2"><button class="ghost2" @click="step = 'netShares'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button><span class="sp"></span><button class="go" :disabled="busy" @click="addShare"><Icon name="plus" :size="15" />{{ lt('Aggiungi «', 'Add «') }}{{ share }}»</button></div>
      </template>

      <!-- a folder of this appliance, simple -->
      <template v-else-if="step === 'folder'">
        <h3>{{ lt('Quale cartella aggiungo?', 'Which folder do I add?') }}</h3>
        <p>{{ lt('Ho guardato dentro questo apparecchio: queste sono le sue cartelle.', 'I looked inside this appliance: these are its folders.') }}</p>
        <div class="list">
          <div v-for="c in cands" :key="c.path" class="pk" :class="{ chosen: chosen === c.path, done: c.inLib }" @click="!c.inLib && (chosen = c.path)">
            <i class="radio"></i><Icon name="folder" :size="20" class="g" />
            <div class="tx"><b>{{ c.name }}</b><span>{{ c.place }} › {{ c.path.split('/').pop() }}</span></div>
            <span v-if="c.inLib" class="ok"><Icon name="check" :size="14" />{{ lt('già nella libreria', 'already in the library') }}</span>
          </div>
          <p v-if="!cands.length" class="muted">{{ lt('Guardo le cartelle…', 'Looking at the folders…') }}</p>
          <div class="pk more" @click="toAdv"><Icon name="list" :size="18" class="g" /><div class="tx"><b>{{ lt('Non è qui? Sfoglia tutte le cartelle', 'Not here? Browse every folder') }}</b><span>{{ lt('Avanzate: albero, colonne, crea una cartella', 'Advanced: tree, columns, make a folder') }}</span></div><Icon name="chevron-right" :size="16" class="g" /></div>
        </div>
        <p v-if="err" class="bad">{{ err }}</p>
        <div class="ft2"><button class="ghost2" @click="step = 'where'"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button><span class="sp"></span>
          <button class="go" :disabled="!chosen || busy" @click="addFolder(chosen)"><Icon name="plus" :size="15" />{{ chosen ? lt('Aggiungi «', 'Add «') + chosen.split('/').pop() + '»' : lt('Aggiungi', 'Add') }}</button></div>
      </template>

      <!-- a folder, advanced: the explorer -->
      <template v-else-if="step === 'adv'">
        <h3 class="adv">{{ lt('Scegli la cartella', 'Pick the folder') }}</h3>
        <Explorer picker :start-at="advStart" :places="m.places" @path="(p) => (advPath = p)" />
        <p v-if="err" class="bad">{{ err }}</p>
        <div class="ft2">
          <div class="chosen"><small>{{ lt('Cartella scelta', 'Chosen folder') }}</small><span>{{ advPath || lt('scegline una a sinistra', 'pick one on the left') }}</span></div>
          <button class="ghost2" @click="toFolder"><Icon name="chevron-left" :size="15" />{{ lt('Indietro', 'Back') }}</button>
          <button class="go" :disabled="!advPath || busy" @click="addFolder(advPath)"><Icon name="plus" :size="15" />{{ lt('Aggiungi questa cartella', 'Add this folder') }}</button>
        </div>
      </template>

      <!-- done -->
      <template v-else>
        <div class="donebox"><span class="ok-c"><Icon name="check" :size="34" /></span><h3>{{ lt('Fatto', 'Done') }}</h3><p>{{ doneText }}</p><button class="go" @click="emit('close')">{{ lt('Chiudi', 'Close') }}</button></div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.am-veil { position: fixed; inset: 0; background: rgba(0,0,0,0.72); display: flex; align-items: center; justify-content: center; z-index: 50; padding: 16px; }
.am { width: 860px; max-width: 100%; max-height: 94vh; overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 22px 26px; box-shadow: 0 25px 50px rgba(0,0,0,0.5); }
.am.big { width: 1120px; }
.go, .ghost2 { display: inline-flex; align-items: center; gap: 7px; border-radius: 10px; font-size: 14px; padding: 9px 15px; }
.go { background: var(--gold); color: #111; border: 0; font-weight: 700; }
.ghost2 { background: var(--light); color: var(--text); border: 0; }
.go:disabled, .ghost2:disabled { opacity: 0.4; }
.sm { padding: 6px 12px; font-size: 13px; }
.g { color: var(--gold); flex: 0 0 auto; }
.w { color: #facc15; flex: 0 0 auto; }
.muted { color: var(--muted); font-size: 13px; }
.gold { color: var(--gold); font-size: 13px; }
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
.seg button { display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 0; color: var(--silver); font-size: 13px; padding: 6px 18px; border-radius: 15px; }
.seg button.on { background: var(--gold); color: #111; font-weight: 700; }
.x { margin-left: auto; background: transparent; border: 0; color: var(--muted); padding: 4px; }
.seg + .x { margin-left: 14px; }
.am h3 { font-size: 23px; margin: 16px 0 6px; font-weight: 700; display: block; }
.am h3.adv { font-size: 21px; margin-bottom: 12px; }
.am p { color: var(--muted); margin: 0 0 14px; font-size: 14px; line-height: 1.5; }
.ch { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.c { display: flex; align-items: center; gap: 14px; padding: 16px; border-radius: 14px; background: var(--bg); border: 1px solid var(--border); cursor: pointer; }
.c:hover { background: var(--light); }
.c.lead { background: rgba(212,175,55,0.10); border: 1.5px solid var(--gold); }
.ci { flex: 0 0 auto; width: 50px; height: 50px; border-radius: 50%; background: var(--gold-dim); color: var(--gold); display: inline-flex; align-items: center; justify-content: center; }
.c.lead .ci { background: var(--gold); color: #111; }
.c div { flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; }
.c b { font-size: 14.5px; }
.c span { color: var(--muted); font-size: 12.5px; }
.chev { color: #666; }
.lbl { display: flex; align-items: center; gap: 8px; margin: 18px 0 8px; font-size: 10.5px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); }
.list { display: flex; flex-direction: column; gap: 8px; max-height: 340px; overflow: auto; }
.line { display: flex; align-items: center; gap: 12px; padding: 10px 12px 10px 14px; border-radius: 10px; background: var(--bg); border: 1px solid var(--border); }
.line div { flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; font-size: 13.5px; min-width: 0; }
.line div span { color: var(--muted); font-size: 12px; }
.ft { display: flex; align-items: center; gap: 8px; border-top: 1px solid var(--border); margin-top: 16px; padding-top: 14px; font-size: 13.5px; flex-wrap: wrap; }
.ft a { color: var(--gold); }
.ft2 { display: flex; align-items: center; gap: 10px; border-top: 1px solid var(--border); margin-top: 16px; padding-top: 14px; flex-wrap: wrap; }
.ft2 .chosen { flex: 1 1 260px; display: flex; flex-direction: column; gap: 3px; font-size: 13.5px; color: var(--gold); min-width: 0; overflow-wrap: anywhere; }
.ft2 .chosen small { font-size: 10.5px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.row2 { display: flex; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
.row2 input { flex: 1 1 200px; }
.auth { padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(212,175,55,0.4); background: rgba(212,175,55,0.06); margin-bottom: 10px; font-size: 14px; }
.chk { display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border); margin: 10px 0; cursor: pointer; }
.chk.on { border-color: rgba(212,175,55,0.5); background: rgba(212,175,55,0.06); }
.chk div { display: flex; flex-direction: column; gap: 3px; font-size: 14px; }
.chk span { color: var(--muted); font-size: 12px; }
.pk { display: flex; align-items: center; gap: 12px; padding: 11px 14px; border-radius: 12px; background: var(--bg); border: 1px solid var(--border); cursor: pointer; }
.pk.chosen { background: rgba(212,175,55,0.10); border: 1.5px solid var(--gold); }
.pk.done { opacity: 0.6; cursor: default; }
.pk .radio { width: 18px; height: 18px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.25); box-sizing: border-box; flex: 0 0 auto; }
.pk.chosen .radio { border-color: var(--gold); background: radial-gradient(circle, var(--gold) 0 3.5px, transparent 4.5px); }
.pk.done .radio { visibility: hidden; }
.pk .tx { flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; font-size: 14px; min-width: 0; }
.pk .tx span { color: var(--muted); font-size: 12px; }
.pk .ok { display: inline-flex; align-items: center; gap: 6px; color: #10b981; font-size: 13px; }
.pk.more { background: transparent; border-color: rgba(255,255,255,0.16); }
.donebox { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 30px 20px; }
.ok-c { width: 70px; height: 70px; border-radius: 50%; background: var(--gold-dim); color: var(--gold); display: inline-flex; align-items: center; justify-content: center; }
@media (max-width: 640px) { .ch { grid-template-columns: 1fr; } }
</style>
