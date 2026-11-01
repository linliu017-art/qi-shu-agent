"use client";
import {useEffect,useRef,useState} from "react";
import {previewData,request,sourceData,sourceList,type Source} from "./lib/client";
import {useApi} from "./lib/use-api";

export function ErrorNotice({message,retry}:{message:string;retry?:()=>void}){return <div className="error" role="alert"><span>{message}</span>{retry&&<button type="button" className="quiet" onClick={retry}>重试读取</button>}</div>}
export function SourceDialog({source,onClose}:{source:Source;onClose:()=>void}){
 const ref=useRef<HTMLDialogElement>(null);const [offset,setOffset]=useState(0);
 const resource=useApi(`/materials/${encodeURIComponent(source.id)}?offset=${offset}`,previewData);
 useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[]);
 return <dialog ref={ref} className="source-dialog" onCancel={onClose} onClose={onClose} aria-labelledby="source-title">
  <header className="panel-heading"><div><span className="eyebrow">参考资料 · 已保存版本</span><h2 id="source-title">{source.name}</h2></div><button type="button" onClick={onClose} aria-label="关闭资料预览">关闭</button></header>
  <div className="dialog-scroll"><p className="note">这是可提取的正文与表格文字；图片、页眉页脚、演讲者备注和图表本身不会读取，Excel 公式不计算。内容可能不完整，请下载原件核对。</p><p className="note">版本 {source.id.slice(0,8)} · {source.kind.toUpperCase()}</p>
   {resource.error&&<ErrorNotice message={resource.error} retry={resource.reload}/>}
   {resource.loading?<p role="status">正在读取资料…</p>:resource.data&&<><p className="note">字符 {resource.data.offset+1}–{resource.data.offset+resource.data.text.length} / {resource.data.total_characters}</p><pre className="source-text">{resource.data.text}</pre></>}
  </div><footer className="panel-footer"><div className="actions"><button type="button" disabled={offset===0||resource.loading} onClick={()=>setOffset(Math.max(0,offset-3000))}>上一段</button><button type="button" disabled={resource.loading||resource.data?.next_offset==null} onClick={()=>setOffset(resource.data!.next_offset!)}>下一段</button></div><a className="button secondary" href={`/api/v1/materials/${source.id}/download`} download>下载原件</a></footer>
 </dialog>
}
export function MaterialLibrary({selected,onToggle,onPreview,onUploaded,compact=false}:{selected:string[];onToggle:(id:string)=>void;onPreview:(source:Source)=>void;onUploaded:(source:Source)=>void;compact?:boolean}){
 const [offset,setOffset]=useState(0);const [uploading,setUploading]=useState(false);const lock=useRef(false);const [error,setError]=useState("");const [notice,setNotice]=useState("");
 const resource=useApi(`/materials?offset=${offset}&limit=12`,sourceList);
 async function upload(file:File|undefined){
  if(!file||lock.current)return;setError("");setNotice("");
  if(!/\.(txt|md|docx|xlsx|pptx)$/i.test(file.name)||file.size>10*1024*1024||!file.size){setError("请选择非空的 TXT、MD、DOCX、XLSX 或 PPTX，单个不超过 10 MB");return}
  lock.current=true;setUploading(true);
  try{const body=new FormData();body.append("file",file);const source=await request("/materials",sourceData,{method:"POST",body},60000);onUploaded(source);setOffset(0);resource.reload();setNotice(`已保存 ${source.name}`)}catch(e){setError(e instanceof Error?e.message:"上传失败")}finally{lock.current=false;setUploading(false)}
 }
 return <section className={compact?"material-picker":"library-content"} aria-label="资料列表">
  <div className="section-title"><div><h2>{compact?"选择参考资料":"你的资料"}</h2><p className="note">{compact?`已选择 ${selected.length}/10 份，锁定当前版本` : "上传原件，随时预览；勾选后可带入新任务。"}</p></div><label className={`button secondary upload-button${uploading?" disabled":""}`}>{uploading?"正在上传…":"＋ 上传资料"}<input type="file" aria-label="上传资料" disabled={uploading} accept=".txt,.md,.docx,.xlsx,.pptx" onChange={event=>{void upload(event.target.files?.[0]);event.target.value=""}}/></label></div>
  <p className="note">支持 TXT / MD / Word / Excel / PPT，单份 10 MB，提取文字最多 20 万字符。图片、页眉页脚、演讲者备注和图表本身不读取，Excel 公式不计算；请使用虚构或脱敏资料。</p>
  {error&&<ErrorNotice message={error}/>}{notice&&<p className="success" role="status">{notice}{selected.length>=10?"；最多选10份，可先移除其他资料。":""}</p>}
  {resource.error&&<ErrorNotice message={resource.error} retry={resource.reload}/>}
  {resource.loading?<p className="loading" role="status">正在读取资料列表…</p>:resource.data?.length===0&&!resource.error?<div className="empty compact material-empty"><span className="empty-mark" aria-hidden="true">▤</span><div><h3>还没有资料</h3><p>可上传参考文件，也可以直接描述目标开始任务。</p></div></div>:<div className="material-rows">{resource.data?.map(source=><div className="material-row" key={source.id}>
   <input type="checkbox" aria-label={`选择 ${source.name}`} checked={selected.includes(source.id)} disabled={!selected.includes(source.id)&&selected.length>=10} onChange={()=>onToggle(source.id)}/><span className="file-icon" aria-hidden="true">▤</span><button type="button" className="file-name" onClick={()=>onPreview(source)}><strong>{source.name}</strong><small>{source.kind.toUpperCase()} · 版本 {source.id.slice(0,8)} · {source.created_at.slice(0,10)}</small></button><button className="quiet" type="button" onClick={()=>onPreview(source)}>预览</button>
  </div>)}</div>}
  {(offset>0||(resource.data?.length??0)>=12)&&<div className="pagination"><button type="button" disabled={!offset||resource.loading} onClick={()=>setOffset(v=>Math.max(0,v-12))}>上一页</button><span>第 {offset/12+1} 页</span><button type="button" disabled={resource.loading||!resource.data||resource.data.length<12} onClick={()=>setOffset(v=>v+12)}>下一页</button></div>}
 </section>
}
