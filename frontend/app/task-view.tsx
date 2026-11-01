"use client";
import {useRef,useState,type FormEvent} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReviewPanel from "./review-panel";
import Versions from "./versions";
import ArtifactEditor from "./artifact-editor";
import PptPreview from "./ppt-preview";
import ExcelPreview from "./excel-preview";
import NativeEditor from "./native-editor";
import NativePptPreview from "./native-ppt-preview";
import {useApi} from "./lib/use-api";
import {editorCapability,editorSession,type EditorSession} from "./lib/native-editor";
import {ErrorNotice} from "./materials";
import {correctionData,documentTitle,isActive,jsonBody,labels,request,shortTitle,taskData,type Source,type Task} from "./lib/client";

export function Markdown({text}:{text:string}){return <div className="document-preview"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]} components={{table:({children})=><div className="table-scroll"><table>{children}</table></div>,a:({children,href})=><a href={href} target="_blank" rel="noopener noreferrer">{children}</a>}}>{text}</ReactMarkdown></div>}
function Downloads({task}:{task:Task}){const office=["xlsx","pptx"].includes(task.artifact_kind||"");const summary=office||task.native_office;return <div className="actions downloads">{office&&<a className="button secondary" href={`/api/v1/tasks/${task.id}/export/${task.artifact_kind}`} download>下载 {task.artifact_kind==="xlsx"?"Excel":"PPT"}</a>}<a className="button" href={`/api/v1/tasks/${task.id}/export/docx`} download>{office?"摘要 Word":"下载 Word"}</a><a className="button" href={`/api/v1/tasks/${task.id}/export/md`} download>{summary?"摘要 Markdown":"下载 Markdown"}</a></div>}
function ResultPanel({task,onPreview,onVersion,reading,onReading}:{task:Task;onPreview:(source:Source)=>void;onVersion:(id:string)=>void;reading:boolean;onReading?:()=>void}){
 const [tab,setTab]=useState("body");const [editing,setEditing]=useState(false);const [nativeSession,setNativeSession]=useState<EditorSession|null>(null);const [nativeError,setNativeError]=useState("");const [nativeBusy,setNativeBusy]=useState(false);const nativeLock=useRef(false);
 const capability=useApi(task.status==="completed"?"/office-editor/capability":null,editorCapability);
 async function openNative(){if(nativeLock.current)return;nativeLock.current=true;setNativeBusy(true);setNativeError("");try{const data=await request('/office-editor/sessions',editorSession,jsonBody({task_id:task.id}));setNativeSession(data)}catch(e){setNativeError(e instanceof Error?e.message:'无法打开编辑器')}finally{nativeLock.current=false;setNativeBusy(false)}}
 return <section className="result-panel" aria-label="成果内容"><header className="panel-heading"><div><span className="eyebrow">{task.status==="waiting"?"等待你的补充":"工作成果"}</span><h2>{task.status==="waiting"?"需要确认的问题":"文档与依据"}</h2></div>{onReading&&<button type="button" onClick={onReading}>{reading?"退出阅读":"展开阅读"}</button>}</header>
  <div className="tabs" role="tablist" aria-label="成果内容页签">{[["body","正文"],["sources",`来源 (${task.sources?.length||0})`],["versions","版本"]].map(([key,label],index)=><button id={`tab-${key}`} key={key} role="tab" aria-controls="result-tab" aria-selected={tab===key} tabIndex={tab===key?0:-1} onClick={()=>setTab(key)} onKeyDown={e=>{if(["ArrowRight","ArrowLeft","Home","End"].includes(e.key)){e.preventDefault();const next=e.key==="Home"?0:e.key==="End"?2:(index+(e.key==="ArrowRight"?1:2))%3;setTab(["body","sources","versions"][next]);(e.currentTarget.parentElement?.children[next] as HTMLElement)?.focus()}}}>{label}</button>)}</div>
  <div id="result-tab" className="document-scroll" role="tabpanel" aria-labelledby={`tab-${tab}`} tabIndex={0}>
   {tab==="body"&&<>{editing?<ArtifactEditor task={task} onSaved={onVersion} onClose={()=>setEditing(false)}/>:<>{task.status==="completed"&&<div className="edit-entry">{capability.data?.enabled?<button type="button" className="secondary" disabled={nativeBusy} onClick={()=>void openNative()}>{nativeBusy?"正在打开…":"直接编辑"}</button>:!task.native_office&&<button type="button" className="secondary" onClick={()=>setEditing(true)}>直接编辑</button>}</div>}{nativeError&&<ErrorNotice message={nativeError}/>} {task.native_office?task.artifact_kind==="pptx"&&capability.data?.enabled&&!nativeSession?<NativePptPreview key={task.id} id={task.id}/>:<div className="empty compact"><h3>完整 Office 原文件</h3><p>{capability.data?.enabled?"使用直接编辑查看和修改完整文件，或下载原文件查看。":"编辑服务尚未就绪；请先下载原文件查看。"}</p></div>:task.status==="completed"&&task.artifact_kind==="pptx"?<PptPreview key={task.id} id={task.id}/>:task.status==="completed"&&task.artifact_kind==="xlsx"?<ExcelPreview key={task.id} id={task.id}/>:<>{task.result?<Markdown text={task.result}/>:<div className="empty"><span className="empty-mark">✦</span><h3>{isActive(task.status)?"启枢正在处理":"还没有成果"}</h3><p>{task.progress}</p></div>}</>}{task.status==="completed"&&<ReviewPanel key={`review-${task.id}`} id={task.id}/>}</>}</>}
   {tab==="sources"&&<><h2>本次任务的参考资料</h2><p className="note">以下是提交时锁定的资料版本。具体引用请结合正文中的标记核对。</p>{task.sources?.length?task.sources.map(source=><button type="button" className="source-card" key={source.id} onClick={()=>onPreview(source)}><span className="file-icon">▤</span><span><strong>{source.name}</strong><small>{source.kind.toUpperCase()} · 版本 {source.id.slice(0,8)} · 点击查看原文</small></span><span>↗</span></button>):<p>没有关联文件。</p>}{task.material&&<details><summary>查看提交时粘贴的参考文字</summary><pre className="source-text">{task.material}</pre></details>}</>}
   {tab==="versions"&&(task.status==="completed"?<Versions key={task.id} id={task.id} onSelect={onVersion}/>:<p className="note">生成完成后可以查看、对比和恢复成果版本。</p>)}
  </div>{task.status==="completed"&&<footer className="panel-footer"><Downloads task={task}/></footer>}{nativeSession&&<NativeEditor session={nativeSession} onClose={()=>setNativeSession(null)} onSaved={id=>{setNativeSession(null);onVersion(id)}}/>}
 </section>
}
export default function TaskView({task,artifact,onPreview,onSelect,onRefresh,onBack,onChanged}:{task:Task;artifact:boolean;onPreview:(source:Source)=>void;onSelect:(id:string,reader?:boolean,focus?:boolean)=>void;onRefresh:()=>void;onBack:()=>void;onChanged:()=>void}){
 const [reading,setReading]=useState(false);const [correction,setCorrection]=useState("");const [notice,setNotice]=useState("");const [error,setError]=useState("");const [busy,setBusy]=useState(false);const lock=useRef(false);
 async function action(kind:"corrections"|"resume"|"cancel"){
  if(lock.current)return;lock.current=true;setBusy(true);setError("");setNotice("");
  try{
   if(kind==="corrections"){const data=await request(`/tasks/${task.id}/corrections`,correctionData,jsonBody({content:correction}));if(data.task)onSelect(data.task.id);else setNotice(data.message||"已保存补充要求");setCorrection("")}
   else{await request(`/tasks/${task.id}/${kind}`,taskData,{method:"POST"});onRefresh()}
   onChanged();
  }catch(e){setError((e instanceof Error?e.message:"操作失败")+"。已回查任务，请核对状态后再操作。");onRefresh();onChanged()}finally{lock.current=false;setBusy(false)}
 }
 function correct(e:FormEvent){e.preventDefault();if(correction.trim())void action("corrections")}
 const reader=artifact||reading;
 return <div className={`task-view${reader?" reading":""}${artifact?" artifact-reader":""}`}>
  {artifact&&<div className="reader-heading"><div><button type="button" className="quiet" onClick={onBack}>← 成果库</button><h1>{documentTitle(task)}</h1><p className="note">{labels[task.status]||task.status} · 独立阅读</p></div><div className="actions"><button type="button" onClick={()=>onSelect(task.id,false)}>查看原任务</button><button type="button" className="primary" onClick={()=>onSelect(task.id,false,true)}>继续修改</button></div></div>}
  {!reader&&<section className="conversation" aria-label="任务工作区"><header className="panel-heading"><div><span className="eyebrow">任务工作台</span><h2>一起把事情推进</h2></div><span className={`status ${task.status}`}>{labels[task.status]||"状态待确认"}</span></header>
   <div className="conversation-scroll"><div className="message user-message"><span className="eyebrow">你的交办</span><p>{shortTitle(task.original_goal||task.goal,800)}</p></div>{task.original_goal&&task.goal!==task.original_goal&&!task.goal.startsWith("原任务：")&&<div className="message user-message"><span className="eyebrow">本轮要求</span><p>{task.goal}</p></div>}<div className="message"><span className="agent-mark">✦ 启枢</span><p role="status">{task.progress}</p><p className="note">{task.status==="completed"?"成果已保存。你可以核对内容，或继续告诉我修改要求。":task.status==="waiting"?"请阅读右侧问题，再在下方回答。":"任务进度会自动更新，离开页面后仍在后台处理。"}</p>{isActive(task.status)&&<button type="button" disabled={busy} onClick={()=>action("cancel")}>停止任务</button>}</div>
    {task.usage&&<p className="usage">输入 {task.usage.input_tokens.toLocaleString()} · 输出 {task.usage.output_tokens.toLocaleString()} token{task.cache_usage&&task.cache_usage.calls>0&&<><br/>{task.cache_usage.reported_calls===0?"缓存命中数据：暂无":`已上报缓存命中 ${task.cache_usage.hit_tokens?.toLocaleString()} token（${task.cache_usage.reported_calls}/${task.cache_usage.calls} 次调用）`}</>}</p>}
    {task.draft&&task.status!=="completed"&&<div className="draft"><h3>章节进度</h3>{task.draft.map(section=><details key={section.position}><summary>{section.position}. {section.title} · {section.content===null?"待完成":"已保存"}</summary>{section.content!==null&&<Markdown text={section.content}/>}</details>)}{["failed","interrupted"].includes(task.status)&&<><button type="button" disabled={busy} onClick={()=>action("resume")}>继续任务</button><p className="note">继续会调用模型；已保存章节会保留。</p></>}</div>}
    {error&&<ErrorNotice message={error}/>} {notice&&<p role="status" className="success">{notice}</p>}
   </div>
   {task.native_office&&<p className="note">完整 Office 成果暂不支持对话修改，请使用原文件编辑器。</p>}
   {!task.native_office&&["queued","running","completed","waiting"].includes(task.status)&&<form className="reply-form" onSubmit={correct}><label htmlFor="correction">{task.status==="waiting"?"回答问题":task.status==="completed"?"修改草稿或回答待确认项":"补充要求"}</label><textarea id="correction" required maxLength={10000} value={correction} onChange={e=>setCorrection(e.target.value)} placeholder="告诉启枢需要补充或调整什么…"/><div className="reply-bottom"><small>发送后会继续处理任务</small><button className="primary" disabled={busy||!correction.trim()} type="submit">{busy?"正在发送…":"发送要求 ↑"}</button></div></form>}
  </section>}
  <ResultPanel key={task.id} task={task} onPreview={onPreview} onVersion={id=>{onSelect(id,artifact);onChanged()}} reading={reader} onReading={artifact?undefined:()=>setReading(v=>!v)}/>
 </div>
}
