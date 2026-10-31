import { defineConfig } from 'astro/config';

// CSP-safe output for FastAPI (script-src 'self'; style-src 'self'):
// never inline stylesheets or small scripts into the HTML.
// `npm run build:app` writes straight into ../app/static (served by StaticFiles(html=True)).
// Dev: /api and /healthz proxy to a local backend on :8010 so the console runs same-origin.
export default defineConfig({
  output: 'static',
  devToolbar: { enabled: false },
  build: { inlineStylesheets: 'never', format: 'directory' },
  vite: {
    build: { assetsInlineLimit: 0 },
    server: {
      proxy: {
        '/api': { target: 'http://127.0.0.1:8010', changeOrigin: false },
        '/healthz': { target: 'http://127.0.0.1:8010', changeOrigin: false },
      },
    },
  },
});
