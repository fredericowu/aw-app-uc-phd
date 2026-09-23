import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base: './' is load-bearing, not a style choice. This bundle is served from
// TWO different roots by the same sub-app: the app's own subdomain
// (aw-app-uc-phd.app.<workspace>, which is what the window opens) and the
// path mount /api/apps/aw-app-uc-phd/. Absolute asset paths work on the first
// and 404 on the second — so the breakage would ship invisibly, since nobody
// routinely opens the prefixed URL. Relative paths work on both.
//
// Single build target. The template's dual lib-mode/standalone config is
// deliberately not carried over: there is no component-mode plugin bundle
// here (see package.json's description).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
});
