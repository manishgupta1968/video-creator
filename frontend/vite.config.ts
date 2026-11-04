import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes inside the Python package so `vg gui` serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../video_generator/web/static", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/files": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
