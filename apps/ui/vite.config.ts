import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const configDir = fileURLToPath(new URL(".", import.meta.url));
const versionCandidates = [
  resolve(configDir, "../../VERSION"),
  resolve(configDir, "VERSION"),
];
const versionPath = versionCandidates.find((candidate) => {
  try {
    readFileSync(candidate, "utf-8");
    return true;
  } catch {
    return false;
  }
});

if (!versionPath) {
  throw new Error("Unable to locate the Encodr VERSION file.");
}

const encodrVersion = readFileSync(versionPath, "utf-8").trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __ENCODR_VERSION__: JSON.stringify(encodrVersion),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.ENCODR_UI_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
    css: true,
  },
});
