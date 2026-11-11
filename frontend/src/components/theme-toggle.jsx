import React,{useEffect,useState} from "react";
import {Moon,Sun} from "lucide-react";
import {Button} from "@/components/ui/button";
function getTheme(){try{const stored=localStorage.getItem("netregress-theme");if(stored==="light"||stored==="dark")return stored;}catch{}return "light";}
export function ThemeToggle(){
 const[theme,setTheme]=useState(getTheme);
 useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem("netregress-theme",theme);}catch{}},[theme]);
 const next=theme==="dark"?"light":"dark",Icon=theme==="dark"?Sun:Moon;
 return <Button variant="ghost" size="icon" aria-label={"Switch to "+next+" theme"} title={"Switch to "+next+" theme"} onClick={()=>setTheme(next)}><Icon size={17}/></Button>;
}
