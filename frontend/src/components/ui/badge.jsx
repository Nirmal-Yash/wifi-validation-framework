import React from "react";
import {cva} from "class-variance-authority";
import {cn} from "@/lib/utils";
export const badgeVariants=cva(
 "inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold leading-none tracking-[.01em] transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
 {variants:{variant:{
  default:"border-transparent bg-primary/15 text-primary",
  secondary:"border-border bg-secondary text-secondary-foreground",
  outline:"border-border text-foreground",
  success:"border-emerald-500/25 bg-emerald-500/10 text-emerald-400",
  warning:"border-amber-500/25 bg-amber-500/10 text-amber-300",
  destructive:"border-rose-500/25 bg-rose-500/10 text-rose-300",
  info:"border-sky-500/25 bg-sky-500/10 text-sky-300",
  muted:"border-border bg-muted text-muted-foreground",
 },},defaultVariants:{variant:"secondary"}}
);
export function Badge({className,variant,...props}){return <span className={cn(badgeVariants({variant}),className)} {...props}/>;}
