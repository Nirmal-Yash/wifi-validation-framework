import React from "react";
import {Slot} from "@radix-ui/react-slot";
import {cva} from "class-variance-authority";
import {Loader2} from "lucide-react";
import {cn} from "@/lib/utils";

export const buttonVariants=cva(
 "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold ring-offset-background transition-[background,color,border-color,box-shadow,transform] duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45 active:translate-y-px [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
 {
  variants:{
   variant:{
    default:"bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
    destructive:"bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
    outline:"border border-input bg-background/70 text-foreground hover:bg-accent hover:text-accent-foreground",
    secondary:"bg-secondary text-secondary-foreground hover:bg-secondary/80",
    ghost:"text-muted-foreground hover:bg-accent hover:text-accent-foreground",
    link:"text-primary underline-offset-4 hover:underline",
   },
   size:{default:"h-9 px-4 py-2",sm:"h-8 rounded-md px-3 text-xs",lg:"h-11 rounded-lg px-6",icon:"size-9 rounded-lg","icon-sm":"size-8 rounded-md"},
  },
  defaultVariants:{variant:"default",size:"default"},
 }
);

export const Button=React.forwardRef(function Button(
 {className,variant,size,asChild=false,loading=false,disabled=false,type="button",children,...props},
 ref
){
 const Comp=asChild?Slot:"button";
 const resolvedVariant=variant==="primary"?"default":variant==="danger"?"destructive":variant;
 return <Comp ref={ref} type={asChild?undefined:type} className={cn(buttonVariants({variant:resolvedVariant,size}),className)} disabled={disabled||loading} aria-busy={loading||undefined} {...props}>
  {loading?<Loader2 className="animate-spin" size={15} aria-hidden="true"/>:null}{children}
 </Comp>;
});
