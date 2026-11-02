import {defineConfig} from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root=path.dirname(fileURLToPath(import.meta.url));

function readPort(name,fallback){
 const raw=process.env[name]||String(fallback);
 if(!/^\d+$/.test(raw))throw new Error(name+" must be an integer port.");
 const value=Number(raw);
 if(!Number.isSafeInteger(value)||value<1024||value>65535)throw new Error(name+" must be between 1024 and 65535.");
 return value;
}

const runnerPort=readPort("NETREGRESS_PORT",5050);
const frontendPort=readPort("NETREGRESS_FRONTEND_PORT",5173);
const apiTarget=process.env.NETREGRESS_API_TARGET||"http://127.0.0.1:"+runnerPort;

export default defineConfig({
 plugins:[react(),tailwindcss()],
 resolve:{alias:{"@":path.resolve(root,"src")}},
 server:{
  host:"127.0.0.1",
  port:frontendPort,
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
