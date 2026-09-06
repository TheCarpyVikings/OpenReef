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
        "automatic-water-change": `${root}features/automatic-water-change/index.html`,
        "icp-import": `${root}features/icp-import/index.html`,
        "camera-intelligence": `${root}features/camera-intelligence/index.html`,
        "tank-diagram": `${root}features/tank-diagram/index.html`,
        "reef-pulse": `${root}features/reef-pulse/index.html`,
        maintenance: `${root}features/maintenance/index.html`,
        "equipment-safety": `${root}features/equipment-safety/index.html`,
        "nps-system": `${root}features/nps-system/index.html`,
        "live-cultures": `${root}features/live-cultures/index.html`,
        "mixing-station": `${root}features/mixing-station/index.html`,
        "cooling-headroom": `${root}features/cooling-headroom/index.html`,
        "feed-timeline": `${root}features/feed-timeline/index.html`,
        "dosing-pumps": `${root}features/dosing-pumps/index.html`,
        "features-hub": `${root}features/index.html`,
        demo: `${root}demo/index.html`,
      },
    },
  },
});
