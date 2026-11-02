import React,{createContext,useCallback,useContext,useEffect,useMemo,useState} from "react";
import {PanelLeftClose,PanelLeftOpen} from "lucide-react";
import {cn} from "@/lib/utils";
import {Button} from "@/components/ui/button";
const Context=createContext(null);
function useSidebar(){const value=useContext(Context);if(!value)throw new Error("Sidebar components must be used inside SidebarProvider.");return value;}
export function SidebarProvider({children,defaultOpen=true}){
 const[open,setOpen]=useState(defaultOpen),[mobileOpen,setMobileOpen]=useState(false);
 const toggle=useCallback(()=>{if(window.matchMedia("(max-width: 900px)").matches)setMobileOpen(value=>!value);else setOpen(value=>!value);},[]);
 useEffect(()=>{const handler=event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="b"){event.preventDefault();toggle();}if(event.key==="Escape")setMobileOpen(false);};window.addEventListener("keydown",handler);return()=>window.removeEventListener("keydown",handler);},[toggle]);
 const value=useMemo(()=>({open,mobileOpen,setMobileOpen,toggle}),[open,mobileOpen,toggle]);
 return <Context.Provider value={value}><div data-sidebar-provider="" data-state={open?"expanded":"collapsed"} data-mobile-open={mobileOpen?"true":"false"} className="flex min-h-svh w-full">{children}</div></Context.Provider>;
}
export function Sidebar({children,className}){
 const{open,mobileOpen,setMobileOpen}=useSidebar();
 return <>{mobileOpen?<button type="button" className="sidebar-backdrop" aria-label="Close navigation" onClick={()=>setMobileOpen(false)}/>:null}<aside data-sidebar="" data-state={open?"expanded":"collapsed"} className={cn("sidebar peer/sidebar",mobileOpen&&"is-mobile-open",className)}>{children}</aside></>;
}
export function SidebarInset({children,className}){return <div className={cn("relative flex min-w-0 flex-1 flex-col bg-background",className)}>{children}</div>;}
export function SidebarHeader({className,...props}){return <div className={cn("sidebar-header",className)} {...props}/>;}
export function SidebarContent({className,...props}){return <div className={cn("sidebar-content",className)} {...props}/>;}
export function SidebarFooter({className,...props}){return <div className={cn("sidebar-footer",className)} {...props}/>;}
export function SidebarGroup({className,...props}){return <div className={cn("sidebar-group",className)} {...props}/>;}
export function SidebarGroupLabel({className,...props}){return <div className={cn("sidebar-group-label",className)} {...props}/>;}
export function SidebarMenu({className,...props}){return <ul className={cn("sidebar-menu",className)} {...props}/>;}
export function SidebarMenuItem({className,...props}){return <li className={cn("sidebar-menu-item",className)} {...props}/>;}
export function SidebarMenuButton({children,isActive=false,tooltip,className,onClick,...props}){
 const{open,setMobileOpen}=useSidebar();
 const handleClick=event=>{setMobileOpen(false);onClick?.(event);};
 return <a className={cn("sidebar-menu-button",isActive&&"active",className)} aria-current={isActive?"page":undefined} data-tooltip={!open?tooltip:undefined} onClick={handleClick} {...props}>{children}</a>;
}
export function SidebarTrigger({className,...props}){
 const{open,toggle}=useSidebar(),Icon=open?PanelLeftClose:PanelLeftOpen;
 return <Button variant="ghost" size="icon" className={cn("sidebar-trigger",className)} aria-label={open?"Collapse sidebar":"Open navigation"} title="Toggle sidebar (Ctrl+B)" onClick={toggle} {...props}><Icon size={17}/></Button>;
}
