import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  resolve: {
    alias: {
      "@ibltools/ibla-loader": fileURLToPath(new URL("../ibla-loader/src/index.ts", import.meta.url)),
      "@ibltools/ktx2-loader": fileURLToPath(new URL("../ktx2-loader/src/index.ts", import.meta.url)),
    },
  },
});
