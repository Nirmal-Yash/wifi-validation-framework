import React from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {Check,ChevronRight,Circle} from "lucide-react";
import {cn} from "@/lib/utils";
export const DropdownMenu=Menu.Root;
export const DropdownMenuTrigger=Menu.Trigger;
export const DropdownMenuGroup=Menu.Group;
export const DropdownMenuPortal=Menu.Portal;
export const DropdownMenuSub=Menu.Sub;
export const DropdownMenuRadioGroup=Menu.RadioGroup;
export const DropdownMenuSubTrigger=React.forwardRef(function DropdownMenuSubTrigger({className,children,inset,...props},ref){return <Menu.SubTrigger ref={ref} className={cn("flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none focus:bg-accent data-[state=open]:bg-accent",inset&&"pl-8",className)} {...props}>{children}<ChevronRight className="ml-auto size-4"/></Menu.SubTrigger>;});
export const DropdownMenuSubContent=React.forwardRef(function DropdownMenuSubContent({className,...props},ref){return <Menu.SubContent ref={ref} className={cn("z-50 min-w-32 overflow-hidden rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-xl animate-menu-in",className)} {...props}/>;});
export const DropdownMenuContent=React.forwardRef(function DropdownMenuContent({className,sideOffset=6,...props},ref){return <Menu.Portal><Menu.Content ref={ref} sideOffset={sideOffset} className={cn("z-50 min-w-48 overflow-hidden rounded-xl border border-border bg-popover p-1.5 text-popover-foreground shadow-xl animate-menu-in",className)} {...props}/></Menu.Portal>;});
export const DropdownMenuItem=React.forwardRef(function DropdownMenuItem({className,inset,variant="default",...props},ref){return <Menu.Item ref={ref} className={cn("relative flex cursor-default select-none items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-40",inset&&"pl-8",variant==="destructive"&&"text-destructive focus:bg-destructive/10 focus:text-destructive",className)} {...props}/>;});
export const DropdownMenuCheckboxItem=React.forwardRef(function DropdownMenuCheckboxItem({className,children,checked,...props},ref){return <Menu.CheckboxItem ref={ref} checked={checked} className={cn("relative flex cursor-default select-none items-center rounded-md py-2 pl-8 pr-2.5 text-sm outline-none focus:bg-accent data-[disabled]:pointer-events-none data-[disabled]:opacity-40",className)} {...props}><span className="absolute left-2 flex size-4 items-center justify-center">{checked?<Check className="size-4"/>:null}</span>{children}</Menu.CheckboxItem>;});
export const DropdownMenuRadioItem=React.forwardRef(function DropdownMenuRadioItem({className,children,...props},ref){return <Menu.RadioItem ref={ref} className={cn("relative flex cursor-default select-none items-center rounded-md py-2 pl-8 pr-2.5 text-sm outline-none focus:bg-accent data-[disabled]:pointer-events-none data-[disabled]:opacity-40",className)} {...props}><span className="absolute left-2 flex size-4 items-center justify-center"><Menu.ItemIndicator><Circle className="size-2.5 fill-current"/></Menu.ItemIndicator></span>{children}</Menu.RadioItem>;});
export function DropdownMenuLabel({className,...props}){return <Menu.Label className={cn("px-2.5 py-2 text-xs font-semibold text-muted-foreground",className)} {...props}/>;}
export function DropdownMenuSeparator({className,...props}){return <Menu.Separator className={cn("-mx-1.5 my-1 h-px bg-border",className)} {...props}/>;}
export function DropdownMenuShortcut({className,...props}){return <span className={cn("ml-auto text-[10px] tracking-widest text-muted-foreground",className)} {...props}/>;}
