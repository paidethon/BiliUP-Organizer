import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8066",
      "/feed": "http://127.0.0.1:8066",
      "/healthz": "http://127.0.0.1:8066",
      "/readyz": "http://127.0.0.1:8066",
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
