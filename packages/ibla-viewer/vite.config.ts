import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    alias: {
      "@ibltools/ibla-loader": fileURLToPath(new URL("../ibla-loader/src/index.ts", import.meta.url)),
    },
  },
});
