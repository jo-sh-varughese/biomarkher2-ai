import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/* The Python backend (app/server.py, or the `biomark` command that wraps it)
   serves this app's assets from /static/, so the built bundle must reference
   them by that absolute path -- not by "/". `--ui-dist` there defaults to
   this project's dist/, and it renders dist/index.html for every
   non-API/non-static path (client-side routing).
   In dev, /api is proxied to the backend so `npm run dev` talks to the real
   thing; when the proxy target is down the app falls back to demo data. The
   backend's own default port is 8000 (app/server.py's --port); keep this in
   step with it, or pass --port to match this file if you change either. */
// Two deployment targets want two different bases, selected by build mode
// rather than by an environment variable -- `VITE_BASE=/ vite build` looks
// portable but Git Bash on Windows rewrites the lone "/" into a filesystem
// path, and the build silently emits assets under /Program Files/Git/.
//   npm run build          -> /static/  (Flask serves assets from its static dir)
//   npm run build:netlify  -> /         (Netlify serves from the domain root)
// A relative base ("./") would satisfy both but breaks client-side routing:
// on /analysis the browser would resolve assets against /analysis/.
export default defineConfig(({ mode }) => ({
  base: mode === "netlify" ? "/" : "/static/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: true,
  },
}));
