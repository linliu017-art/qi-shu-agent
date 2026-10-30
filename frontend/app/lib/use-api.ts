"use client";
import {useEffect,useState} from "react";
import {request} from "./client";
export function useApi<T>(path:string|null,decode:(value:unknown)=>T,poll:boolean|((data:T)=>boolean)=false){
 const [state,setState]=useState<{path:string|null;data:T|null;error:string;loading:boolean}>({path:null,data:null,error:"",loading:true});
 const [revision,setRevision]=useState(0);
 useEffect(()=>{
  if(!path)return;
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;let continuePolling=Boolean(poll);
  async function load(){
   try{const data=await request(path!,decode,{signal:controller.signal});if(!controller.signal.aborted){continuePolling=typeof poll==="function"?poll(data):poll;setState({path,data,error:"",loading:false})}}
   catch(error){if(!controller.signal.aborted)setState(prev=>({path,data:prev.path===path?prev.data:null,error:error instanceof Error?error.message:"读取失败",loading:false}))}
   finally{if(continuePolling&&!controller.signal.aborted)timer=setTimeout(load,document.hidden?10000:1500)}
  }
  void Promise.resolve().then(()=>{if(!controller.signal.aborted){setState(prev=>({path,data:prev.path===path?prev.data:null,error:"",loading:true}));void load()}});
  return()=>{controller.abort();clearTimeout(timer)};
 },[path,decode,revision,poll]);
 return {...(state.path===path?state:{path,data:null,error:"",loading:Boolean(path)}),reload:()=>setRevision(v=>v+1)};
}
