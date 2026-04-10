import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  resolve: {
    alias: {
      "@ibltools/ktx2-loader": fileURLToPath(new URL("../ktx2-loader/src/index.ts", import.meta.url)),
    },
  },
});
