"use client";
import {useEffect,useState} from 'react';
import {request,jsonBody} from './lib/client';
import {editorSession} from './lib/native-editor';

type Viewer={destroyEditor:()=>void};
type ViewerWindow=Window & {DocsAPI?:{DocEditor:new(id:string,config:Record<string,unknown>)=>Viewer}};

/** The actual presentation is rendered by the local Office service in view mode. */
export default function NativePptPreview({id}:{id:string}){
 const [error,setError]=useState('');const [ready,setReady]=useState(false);
 useEffect(()=>{
  let cancelled=false;let viewer:Viewer|null=null;let script:HTMLScriptElement|null=null;
  async function open(){
   try{
    const session=await request('/office-editor/sessions',editorSession,jsonBody({task_id:id,mode:'view'}));
    if(cancelled)return;
    script=document.createElement('script');script.src=session.editor_origin+'/web-apps/apps/api/documents/api.js';script.async=true;
    script.onerror=()=>{if(!cancelled)setError('无法连接本机预览服务，请下载原文件查看。')};
    script.onload=()=>{
     if(cancelled)return;const api=(window as ViewerWindow).DocsAPI;
     if(!api){setError('无法打开预览，请下载原文件查看。');return}
     try{viewer=new api.DocEditor('native-ppt-preview-'+id,{...session.config,events:{onDocumentReady:()=>{if(!cancelled)setReady(true)},onError:()=>{if(!cancelled)setError('预览加载失败，请下载原文件查看。')}}})}catch{setError('预览加载失败，请下载原文件查看。')}
    };
    document.head.appendChild(script);
   }catch{if(!cancelled)setError('无法打开预览，请下载原文件查看。')}
  }
  void open();return()=>{cancelled=true;viewer?.destroyEditor();script?.remove()};
 },[id]);
 return <div className="native-ppt-preview" aria-label="幻灯片预览">{error?<p className="error" role="alert">{error}</p>:!ready&&<p className="note" role="status">正在打开幻灯片预览…</p>}<div className="native-ppt-frame"><div id={'native-ppt-preview-'+id}/></div></div>;
}
