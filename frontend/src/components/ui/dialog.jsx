import React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {X} from "lucide-react";
import {cn} from "@/lib/utils";
export const Dialog=DialogPrimitive.Root;
export const DialogTrigger=DialogPrimitive.Trigger;
export const DialogPortal=DialogPrimitive.Portal;
export const DialogClose=DialogPrimitive.Close;
export const DialogOverlay=React.forwardRef(function DialogOverlay({className,...props},ref){
 return <DialogPrimitive.Overlay ref={ref} className={cn("fixed inset-0 z-50 bg-black/65 backdrop-blur-[3px] animate-overlay-in",className)} {...props}/>;
});
export const DialogContent=React.forwardRef(function DialogContent({className,children,showClose=true,...props},ref){
 return <DialogPortal><DialogOverlay/><DialogPrimitive.Content ref={ref} className={cn("fixed left-1/2 top-1/2 z-50 grid w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-2xl border border-border bg-popover p-6 text-popover-foreground shadow-2xl outline-none animate-dialog-in",className)} {...props}>
  {children}{showClose?<DialogPrimitive.Close className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Close dialog"><X size={16}/><span className="sr-only">Close</span></DialogPrimitive.Close>:null}
 </DialogPrimitive.Content></DialogPortal>;
});
export function DialogHeader({className,...props}){return <div className={cn("flex flex-col gap-1.5 text-left",className)} {...props}/>;}
export function DialogFooter({className,...props}){return <div className={cn("mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",className)} {...props}/>;}
export const DialogTitle=React.forwardRef(function DialogTitle({className,...props},ref){return <DialogPrimitive.Title ref={ref} className={cn("text-lg font-semibold tracking-tight",className)} {...props}/>;});
export const DialogDescription=React.forwardRef(function DialogDescription({className,...props},ref){return <DialogPrimitive.Description ref={ref} className={cn("text-sm leading-6 text-muted-foreground",className)} {...props}/>;});
