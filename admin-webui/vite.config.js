import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

// Built to ./dist and served by webui_server.py from /opt/hifi-webui/dist.
// Relative base so it works regardless of the mount path; the API lives on the
// same origin (webui_server proxies /api/* to the loopback services).
// Two pages share the build: the web admin (index.html) and the Library
// editor (library.html, served by webui_server on /library), so the two share
// one set of chunks (api.js, i18n) and the same origin, session and CSRF.
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        library: fileURLToPath(new URL('./library.html', import.meta.url)),
      },
    },
  },
  server: {
    port: 5273,
    // In dev, proxy /api to a locally-running webui_server (HIFI_WEBUI_HTTP_ONLY=1).
    proxy: { '/api': 'http://localhost:8081' },
  },
});
