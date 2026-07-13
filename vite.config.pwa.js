import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { resolve } from 'path';
import { readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf-8'));

// Separate build target from vite.config.js (the Electron kiosk build).
// Produces an installable PWA served over LAN by sources_server.py at
// /app/ — see sources_server.py's static route and the "Copertura iOS"
// plan. Kept as its own config (rather than a second Rollup input on the
// existing config) because only this target needs vite-plugin-pwa/Workbox
// registered.
// The project root also has index.html (the Electron kiosk's entry) sitting
// right next to pwa.html. Vite's dev/preview servers serve index.html by
// default at "/" — without this, opening the bare LAN address in a browser
// silently shows the kiosk instead of the PWA. Redirect "/" to /pwa.html
// only for this config's dev/preview servers (production hosting under
// sources_server.py's /app/ only ever serves pwa-dist, so this doesn't
// apply there).
const redirectRootToPwaHtml = () => ({
  name: 'redirect-root-to-pwa-html',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url === '/') { res.writeHead(302, { Location: '/pwa.html' }); res.end(); return; }
      next();
    });
  },
  configurePreviewServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url === '/') { res.writeHead(302, { Location: '/pwa.html' }); res.end(); return; }
      next();
    });
  },
});

export default defineConfig({
  plugins: [
    react(),
    redirectRootToPwaHtml(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: null, // registered manually in src/main.pwa.jsx
      manifest: {
        name: 'Osmium Sound',
        short_name: 'Osmium Sound',
        description: 'Telecomando per il tuo HiFi Player',
        start_url: '/app/',
        scope: '/app/',
        display: 'standalone',
        background_color: '#0a0a0a',
        theme_color: '#0a0a0a',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Precache the app shell only; player control traffic (jsonrpc.js)
        // and appliance-management calls (/api/*) must always hit the
        // network live, never be served stale from cache.
        globPatterns: ['**/*.{js,css,html,png,svg,ico}'],
        navigateFallbackDenylist: [/^\/api\//, /jsonrpc\.js/],
        runtimeCaching: [
          {
            urlPattern: /\/jsonrpc\.js/,
            handler: 'NetworkOnly',
          },
          {
            urlPattern: /\/api\//,
            handler: 'NetworkOnly',
          },
        ],
      },
    }),
  ],
  // Relative base (matches vite.config.js) so the built bundle works no
  // matter which path prefix sources_server.py ends up serving it from —
  // only the manifest's start_url/scope (below) need to know that prefix.
  base: './',
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    outDir: 'pwa-dist',
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, 'pwa.html'),
    },
  },
  server: {
    port: 5174,
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
});
