import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const PY_DIST = path.resolve(__dirname, "../src/seerflow/web/dist");

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    outDir: PY_DIST,
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
