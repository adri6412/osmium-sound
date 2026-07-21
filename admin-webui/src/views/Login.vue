<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';

const router = useRouter();
const username = ref('');
const password = ref('');
const busy = ref(false);
const error = ref('');

onMounted(async () => {
  const { data } = await api.authStatus();
  if (data.logged_in) router.push('/');
  else if (!data.has_account) router.push('/setup');
});

async function submit() {
  busy.value = true; error.value = '';
  const { ok, data } = await api.login(username.value, password.value);
  busy.value = false;
  if (ok && data.success) router.push('/');
  else error.value = data.message || 'Accesso fallito';
}
</script>

<template>
  <div class="center">
    <div class="card" style="width: 350px;">
      <h3><span class="dot"></span>Accedi</h3>
      <p class="sub">Interfaccia di amministrazione del dispositivo.</p>
      <label>Nome utente</label>
      <input v-model="username" @keyup.enter="submit" autocomplete="username" />
      <label>Password</label>
      <input v-model="password" type="password" @keyup.enter="submit" autocomplete="current-password" />
      <div style="margin-top: 16px;">
        <button :disabled="busy" @click="submit" style="width: 100%;">{{ busy ? '…' : 'Accedi' }}</button>
      </div>
      <div v-if="error" class="msg err">{{ error }}</div>
      <p class="muted" style="margin-top: 14px;">Password dimenticata? Usa lo schermo del dispositivo (Impostazioni → Reset password interfaccia web) oppure il ripristino di fabbrica.</p>
    </div>
  </div>
</template>
