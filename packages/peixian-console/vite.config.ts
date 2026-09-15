import { defineConfig } from "vite"
import solid from "vite-plugin-solid"
import project from "../../framework/project.json"
export default defineConfig({
  plugins: [solid()],
  server: {
    port: 5179,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${project.console_port}`, changeOrigin: false } },
  },
  build: { outDir: "dist", emptyOutDir: true },
})
