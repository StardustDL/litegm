import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served by the gateway itself under /admin, so ``base`` must
// match the configured admin path. During development, proxy API calls to the
// running gateway.
export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/admin/api": "http://127.0.0.1:8080",
      "/v1": "http://127.0.0.1:8080",
    },
  },
});
