"use client";
import {useEffect,useRef,useState} from 'react';
import {editorDecision,editorStatus,type EditorSession} from './lib/native-editor';
import {request} from './lib/client';

type EditorInstance={requestClose:()=>void;destroyEditor:()=>void};
type EditorWindow=Window & {DocsAPI?:{DocEditor:new(id:string,config:Record<string,unknown>)=>EditorInstance}};
export default function NativeEditor({session,onSaved,onClose}:{session:EditorSession;onSaved:(id:string)=>void;onClose:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null),instance=useRef<EditorInstance|null>(null);const [ready,setReady]=useState(false),[dirty,setDirty]=useState(false),[closing,setClosing]=useState(false),[detached,setDetached]=useState(false),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[warnings,setWarnings]=useState<string[]>([]),[approving,setApproving]=useState(false);
 useEffect(()=>{const node=dialog.current;node?.showModal();const warn=(event:BeforeUnloadEvent)=>{event.preventDefault()};window.addEventListener('beforeunload',warn);return()=>{window.removeEventListener('beforeunload',warn);instance.current?.destroyEditor();node?.close()}},[]);
 useEffect(()=>{
  let cancelled=false;const script=document.createElement('script');script.src=session.editor_origin+'/web-apps/apps/api/documents/api.js';script.async=true;
  script.onerror=()=>{if(!cancelled)setError('无法连接本机编辑服务，请检查服务后重试。')};
  script.onload=()=>{if(cancelled)return;const api=(window as EditorWindow).DocsAPI;if(!api){setError('编辑服务响应异常，请稍后重试。');return}
   try{instance.current=new api.DocEditor('native-office-'+session.session_id,{...session.config,events:{onDocumentReady:()=>setReady(true),onDocumentStateChange:(event:{data:boolean})=>setDirty(Boolean(event.data)),onError:()=>setError('编辑器报告错误，请检查文件和编辑服务。'),onRequestClose:()=>{instance.current?.destroyEditor();instance.current=null;setDetached(true);setClosing(true)}}})}catch{setError('编辑器启动失败，请稍后重试。')}
  };document.head.appendChild(script);return()=>{cancelled=true;script.remove()}
 },[session]);
 useEffect(()=>{
  if(!closing)return;let cancelled=false;let timer:ReturnType<typeof setTimeout>;const start=Date.now();
  async function poll(){try{const status=await request(`/office-editor/sessions/${session.session_id}`,editorStatus);if(cancelled)return;if(['saved','unchanged'].includes(status.status)&&status.task_id){onSaved(status.task_id);return}if(status.status==='conflict'||status.status==='failed'){setConflict(true);setError(status.status==='failed'?'编辑结果未能保存为版本，请先下载本次编辑结果；原文件仍然保留。':'成果已出现新版本，本次编辑未覆盖。请下载本次编辑结果后再处理。');setClosing(false);return}if(status.status==='review_required'){setWarnings(status.warnings);setError('检测到部分复杂内容可能发生变化。请先下载检查，确认后再保存；原版本会保留。');setClosing(false);return}if(Date.now()-start>60000){setError('编辑结果仍在保存，请稍后重试查询。');setClosing(false);return}}catch{if(cancelled)return;setError('暂时无法读取保存状态，请重试查询。');setClosing(false);return}timer=setTimeout(poll,1500)}
  void poll();return()=>{cancelled=true;clearTimeout(timer)}
 },[closing,onSaved,session.session_id]);
 async function approve(){if(approving)return;setApproving(true);try{const result=await request(`/office-editor/sessions/${session.session_id}/approve`,editorDecision,{method:'POST'});if(result.status==='saved'&&result.task_id){onSaved(result.task_id);return}if(result.status==='conflict'){setWarnings([]);setConflict(true);setError('成果已出现新版本，本次编辑未覆盖。请下载本次编辑结果后再处理。')}}catch{setError('未能保存，请下载本次编辑结果并稍后重试。')}finally{setApproving(false)}}
 function close(){if(warnings.length){if(window.confirm('放弃将本次编辑保存为新版本？建议先下载编辑结果。'))onClose();return}if(instance.current&&ready){instance.current.requestClose();return}if(!ready&&!closing)onClose()}
 return <dialog ref={dialog} className="native-office-dialog" aria-label="Office文件编辑器" onCancel={event=>{event.preventDefault();close()}}>
  <header className="native-office-header"><div><strong>编辑 Office 文件</strong><span>{closing?'正在保存，请稍候':dirty?'正在同步修改…':ready?'修改会保存为新版本':'正在打开编辑器…'}</span></div><button type="button" disabled={closing||dirty||approving} onClick={close}>{closing?'保存中…':ready?'保存并退出':'关闭'}</button></header>
  {error&&<div className="native-office-alert" role="alert"><span>{error}</span>{warnings.length>0&&<ul>{warnings.map(item=><li key={item}>{item}</li>)}</ul>}{(conflict||warnings.length>0)?<a className="button secondary" href={`/api/v1/office-editor/sessions/${session.session_id}/recovery`} download>下载本次编辑结果</a>:detached&&<button type="button" onClick={()=>{setError('');setClosing(true)}}>重新查询保存状态</button>}{warnings.length>0&&<button type="button" disabled={approving} onClick={()=>void approve()}>{approving?'正在保存…':'确认后保存为新版本'}</button>}{conflict&&<button type="button" onClick={onClose}>返回成果</button>}</div>}
  <div className="native-office-body"><div id={'native-office-'+session.session_id}/></div>
 </dialog>
}
