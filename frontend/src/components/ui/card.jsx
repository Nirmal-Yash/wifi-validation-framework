import React from "react";
import {cn} from "@/lib/utils";
export function Card({className,...props}){return <section className={cn("rounded-xl border border-border bg-card text-card-foreground shadow-card",className)} {...props}/>;}
export function CardHeader({className,...props}){return <div className={cn("flex flex-col gap-1.5 p-5 pb-4",className)} {...props}/>;}
export function CardTitle({className,...props}){return <h2 className={cn("text-sm font-semibold tracking-tight",className)} {...props}/>;}
export function CardDescription({className,...props}){return <p className={cn("text-xs leading-5 text-muted-foreground",className)} {...props}/>;}
export function CardContent({className,...props}){return <div className={cn("px-5 pb-5",className)} {...props}/>;}
export function CardFooter({className,...props}){return <div className={cn("flex items-center gap-2 border-t border-border px-5 py-3",className)} {...props}/>;}
