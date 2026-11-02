import React from "react";
import * as Primitive from "@radix-ui/react-tabs";
import {cn} from "@/lib/utils";
export const Tabs=Primitive.Root;
export const TabsList=React.forwardRef(function TabsList({className,...props},ref){return <Primitive.List ref={ref} className={cn("inline-flex h-10 items-center justify-start gap-1 rounded-lg border border-border bg-muted/60 p-1 text-muted-foreground",className)} {...props}/>;});
export const TabsTrigger=React.forwardRef(function TabsTrigger({className,...props},ref){return <Primitive.Trigger ref={ref} className={cn("inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md px-3 text-xs font-medium outline-none transition-all focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm",className)} {...props}/>;});
export const TabsContent=React.forwardRef(function TabsContent({className,...props},ref){return <Primitive.Content ref={ref} className={cn("mt-4 outline-none focus-visible:ring-2 focus-visible:ring-ring",className)} {...props}/>;});
