import React from "react";
import {cn} from "@/lib/utils";
export const Input=React.forwardRef(function Input({className,type="text",...props},ref){
 return <input ref={ref} type={type} className={cn("flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50",className)} {...props}/>;
});
export const Textarea=React.forwardRef(function Textarea({className,...props},ref){
 return <textarea ref={ref} className={cn("flex min-h-24 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50",className)} {...props}/>;
});
