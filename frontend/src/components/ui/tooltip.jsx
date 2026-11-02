import React from "react";
import * as Primitive from "@radix-ui/react-tooltip";
import {cn} from "@/lib/utils";
export const TooltipProvider=({delayDuration=300,...props})=><Primitive.Provider delayDuration={delayDuration} {...props}/>;
export const Tooltip=Primitive.Root;
export const TooltipTrigger=Primitive.Trigger;
export const TooltipContent=React.forwardRef(function TooltipContent({className,sideOffset=5,children,...props},ref){
 return <Primitive.Portal><Primitive.Content ref={ref} sideOffset={sideOffset} className={cn("z-[100] overflow-hidden rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl animate-menu-in",className)} {...props}><Primitive.Arrow className="fill-popover"/>{children}</Primitive.Content></Primitive.Portal>;
});
