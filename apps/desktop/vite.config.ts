import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    proxy: {
      "/v1": "http://127.0.0.1:8088",
      "/health": "http://127.0.0.1:8088",
    },
  },
});
