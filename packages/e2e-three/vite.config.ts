import path from "node:path";

import { defineConfig } from "vite";

const repoRoot = path.resolve(import.meta.dirname, "..", "..");

export default defineConfig({
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
});
