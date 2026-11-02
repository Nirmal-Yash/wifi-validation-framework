import {defineConfig} from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root=path.dirname(fileURLToPath(import.meta.url));
const runnerPort=process.env.NETREGRESS_PORT||"5000";
const apiTarget=process.env.NETREGRESS_API_TARGET||`http://127.0.0.1:${runnerPort}`;

export default defineConfig({
 plugins:[react(),tailwindcss()],
 resolve:{alias:{"@":path.resolve(root,"src")}},
 server:{
  host:"127.0.0.1",
  port:5173,
  strictPort:true,
  proxy:{"/api":{target:apiTarget,changeOrigin:true}},
 },
 build:{outDir:"dist",sourcemap:false,cssMinify:true},
 test:{
  environment:"jsdom",
  globals:true,
  css:true,
  setupFiles:["./src/test/setup.js"],
  include:["src/**/*.{test,spec}.{js,jsx}"],
  restoreMocks:true,
  clearMocks:true,
 },
});
