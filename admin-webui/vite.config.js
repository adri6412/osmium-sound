import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Built to ./dist and served by webui_server.py from /opt/hifi-webui/dist.
// Relative base so it works regardless of the mount path; the API lives on the
// same origin (webui_server proxies /api/* to the loopback services).
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5273,
    // In dev, proxy /api to a locally-running webui_server (HIFI_WEBUI_HTTP_ONLY=1).
    proxy: { '/api': 'http://localhost:8081' },
  },
});
