import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5522,
    watch: {
      // OneDrive / network drives often miss native FS events
      usePolling: true,
      interval: 1000,
    },
    hmr: {
      overlay: true,
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
