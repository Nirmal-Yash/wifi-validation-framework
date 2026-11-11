import React from "react";
import {createRoot} from "react-dom/client";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {SessionProvider} from "@/auth/session-provider";
import SessionExpiryDialog from "@/auth/session-dialog";
import {TooltipProvider} from "@/components/ui/tooltip";
import App from "@/App";
import "@/styles.css";
import "@/styles/tokens.css";
import "@/styles/product-shell.css";

export const queryClient=new QueryClient({
 defaultOptions:{
  queries:{
   staleTime:5000,gcTime:5*60*1000,
   refetchOnWindowFocus:true,refetchOnReconnect:true,
   retry:(failureCount,error)=>error?.status>=400&&error?.status<500?false:failureCount<1,
  },
  mutations:{retry:false},
 },
});
function Root(){
 return <QueryClientProvider client={queryClient}><SessionProvider><TooltipProvider delayDuration={300}><App/><SessionExpiryDialog/></TooltipProvider></SessionProvider></QueryClientProvider>;
}
createRoot(document.getElementById("root")).render(<React.StrictMode><Root/></React.StrictMode>);
