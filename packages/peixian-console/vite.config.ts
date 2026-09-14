import { defineConfig } from "vite"
import solid from "vite-plugin-solid"
export default defineConfig({
  plugins: [solid()],
  server: {
    port: 5178,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:14090", changeOrigin: false } },
  },
  build: { outDir: "dist", emptyOutDir: true },
})
