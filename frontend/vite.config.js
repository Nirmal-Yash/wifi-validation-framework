import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const runnerPort = process.env.NETREGRESS_PORT || "5000";
const apiTarget = process.env.NETREGRESS_API_TARGET || `http://127.0.0.1:${runnerPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    css: true,
    include: ["src/**/*.{test,spec}.{js,jsx}"],
  },
});
