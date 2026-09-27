import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built UI is written into the Python package so end users never need Node.js.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/asthra/web/dist", emptyOutDir: true, chunkSizeWarningLimit: 6000 },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "jsdom" },
} as any);
