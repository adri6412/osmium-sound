<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { useI18n } from '../i18n';
import LanguageSelector from '../components/LanguageSelector.vue';

const router = useRouter();
const { t } = useI18n();
const username = ref('');
const password = ref('');
const busy = ref(false);
const error = ref('');

onMounted(async () => {
  // Same rule as the router guard in main.js: if the status call itself fails,
  // stay on the login form rather than reading `undefined` and bouncing into
  // the setup wizard.
  const { ok, data } = await api.authStatus();
  if (!ok) return;
  if (data.logged_in) router.push('/');
  else if (!data.has_account) router.push('/setup');
});

async function submit() {
  busy.value = true; error.value = '';
  const { ok, data } = await api.login(username.value, password.value);
  busy.value = false;
  if (ok && data.success) router.push('/');
  else error.value = data.message || t('auth.loginFailed');
}
</script>

<template>
  <div class="center">
    <div style="width: 350px;">
      <LanguageSelector variant="compact" />
      <div class="card">
        <h3><span class="dot"></span>{{ t('auth.loginTitle') }}</h3>
        <p class="sub">{{ t('auth.loginSubtitle') }}</p>
        <label>{{ t('auth.username') }}</label>
        <input v-model="username" @keyup.enter="submit" autocomplete="username" />
        <label>{{ t('auth.password') }}</label>
        <input v-model="password" type="password" @keyup.enter="submit" autocomplete="current-password" />
        <div style="margin-top: 16px;">
          <button :disabled="busy" @click="submit" style="width: 100%;">{{ busy ? t('auth.signingIn') : t('auth.signIn') }}</button>
        </div>
        <div v-if="error" class="msg err">{{ error }}</div>
        <p class="muted" style="margin-top: 14px;">{{ t('auth.forgotHint') }}</p>
      </div>
    </div>
  </div>
</template>
