import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = fileURLToPath(new URL("../..", import.meta.url));
const encodrVersion = readFileSync(resolve(projectRoot, "VERSION"), "utf-8").trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __ENCODR_VERSION__: JSON.stringify(encodrVersion),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
    css: true,
  },
});
