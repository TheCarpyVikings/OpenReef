import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = fileURLToPath(new URL(".", import.meta.url));

// Multi-page build: the dive stays the homepage; each deep-dive feature page
// is its own static HTML entry so it indexes (and loads) on its own.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: `${root}index.html`,
        "coral-spawning": `${root}features/coral-spawning/index.html`,
        "dosing-advisor": `${root}features/dosing-advisor/index.html`,
      },
    },
  },
});
