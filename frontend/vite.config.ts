import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import monacoEditorPluginImport from "vite-plugin-monaco-editor";

const PY_DIST = path.resolve(__dirname, "../src/seerflow/web/dist");

// `vite-plugin-monaco-editor` ships as CJS — under Node ESM resolution the
// callable plugin lives on `.default`. Tolerate both shapes so we work no
// matter which interop the bundler picks at install time.
const monacoEditorPlugin =
  (monacoEditorPluginImport as unknown as {
    default?: typeof monacoEditorPluginImport;
  }).default ?? monacoEditorPluginImport;

export default defineConfig({
  plugins: [
    react(),
    // YAML syntax highlighting is built into monaco's core editor; no
    // separate language worker is required (and `vite-plugin-monaco-editor`
    // does not ship a `yaml` worker definition). We only need the base
    // editor worker to avoid the "language services unavailable" warning.
    monacoEditorPlugin({
      languageWorkers: ["editorWorkerService"],
    }),
  ],
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
