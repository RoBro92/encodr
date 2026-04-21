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
const defaultAllowedHosts = ["127.0.0.1", "localhost"];

function resolveAllowedHosts(): true | string[] {
  const configuredHosts = process.env.ENCODR_UI_ALLOWED_HOSTS?.trim();
  if (!configuredHosts) {
    return defaultAllowedHosts;
  }

  if (configuredHosts === "*") {
    return true;
  }

  const parsedHosts = configuredHosts
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);

  return parsedHosts.length > 0 ? parsedHosts : defaultAllowedHosts;
}

const allowedHosts = resolveAllowedHosts();

function extractRequestHost(hostHeader: string | undefined): string {
  if (!hostHeader) {
    return "";
  }
  return hostHeader.replace(/:\d+$/, "").trim().toLowerCase();
}

function isSafeDisplayHost(host: string): boolean {
  return /^[a-z0-9._-]+$/i.test(host);
}

function isAllowedHost(host: string): boolean {
  if (!host) {
    return false;
  }
  if (allowedHosts === true) {
    return true;
  }
  return allowedHosts.some((candidate) => candidate.toLowerCase() === host);
}

function blockedHostResponse(host: string): string {
  const command =
    host && isSafeDisplayHost(host)
      ? `  encodr addhost ${host}`
      : "  encodr addhost your.domain.example";
  return [
    `Blocked request. The UI host "${host}" is not allowed.`,
    "",
    "From the Encodr root console, run:",
    command,
    "",
    "This will add the host to allowed hosts and recreate the stack.",
  ].join("\n");
}

function allowedHostPlugin() {
  const applyMiddleware = (middlewares: { use: (handler: (req: any, res: any, next: () => void) => void) => void }) => {
    middlewares.use((req, res, next) => {
      const host = extractRequestHost(req.headers.host);
      if (isAllowedHost(host)) {
        next();
        return;
      }

      res.statusCode = 403;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      res.end(blockedHostResponse(host || "unknown"));
    });
  };

  return {
    name: "encodr-allowed-hosts",
    configureServer(server: { middlewares: { use: (handler: (req: any, res: any, next: () => void) => void) => void } }) {
      applyMiddleware(server.middlewares);
    },
    configurePreviewServer(server: { middlewares: { use: (handler: (req: any, res: any, next: () => void) => void) => void } }) {
      applyMiddleware(server.middlewares);
    },
  };
}

export default defineConfig({
  plugins: [react(), allowedHostPlugin()],
  define: {
    __ENCODR_VERSION__: JSON.stringify(encodrVersion),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.ENCODR_UI_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
    css: true,
  },
});
