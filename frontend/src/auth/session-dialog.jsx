import React from "react";
import {Clock3,LogOut,ShieldCheck} from "lucide-react";
import {useSession} from "@/auth/session-provider";
import {Button} from "@/components/ui/button";
import {Dialog,DialogContent,DialogDescription,DialogFooter,DialogHeader,DialogTitle} from "@/components/ui/dialog";

export default function SessionExpiryDialog(){
 const{warningVisible,idleRemaining,continueSession,logout}=useSession();
 const minutes=Math.floor(idleRemaining/60000),seconds=Math.floor((idleRemaining%60000)/1000);
 return <Dialog open={warningVisible} onOpenChange={()=>{}}>
  <DialogContent showClose={false} onEscapeKeyDown={event=>event.preventDefault()} onPointerDownOutside={event=>event.preventDefault()} onInteractOutside={event=>event.preventDefault()}>
   <div className="session-dialog-icon"><Clock3 size={20}/></div>
   <DialogHeader><DialogTitle>Still working?</DialogTitle><DialogDescription>Your NetRegress session will end soon because there has been no activity. Continue to keep working, or sign out now.</DialogDescription></DialogHeader>
   <div className="session-countdown"><span>Automatic sign-out in</span><strong>{String(minutes).padStart(2,"0")}:{String(seconds).padStart(2,"0")}</strong></div>
   <div className="session-security-note"><ShieldCheck size={15}/> Your login is held in an HttpOnly session cookie. No session token is stored in browser storage.</div>
   <DialogFooter><Button variant="ghost" onClick={logout}><LogOut size={14}/>Sign out</Button><Button onClick={()=>{
    const result=continueSession();
    if(result&&typeof result.catch==="function")result.catch(()=>{});
   }}>Continue session</Button></DialogFooter>
  </DialogContent>
 </Dialog>;
}
