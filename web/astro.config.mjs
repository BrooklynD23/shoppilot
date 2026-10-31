import { defineConfig } from 'astro/config';

// CSP-safe output for FastAPI (script-src 'self'; style-src 'self'):
// never inline stylesheets or small scripts into the HTML.
export default defineConfig({
  output: 'static',
  devToolbar: { enabled: false },
  build: { inlineStylesheets: 'never', format: 'directory' },
  vite: { build: { assetsInlineLimit: 0 } },
});
