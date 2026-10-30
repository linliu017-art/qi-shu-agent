"use client";
import {useEffect,useRef,useState,useSyncExternalStore,type FormEvent,type KeyboardEvent} from "react";
import FileDrop from "./file-drop";
import {ErrorNotice,MaterialLibrary,SourceDialog} from "./materials";
import TaskView from "./task-view";
import {artifactList,isActive,pollTask,jsonBody,labels,request,shortTitle,taskData,threadList,type Source} from "./lib/client";
import {createGate,emptyDraft,parseRoute,prepareSubmission,restoreDraft,routeHash,type Draft,type View} from "./lib/navigation";
import {useApi} from "./lib/use-api";
const draftKey="qi-shu-draft-v1",requestKey="qi-shu-submission-v1";
function subscribe(listener:()=>void){window.addEventListener("hashchange",listener);window.addEventListener("popstate",listener);return()=>{window.removeEventListener("hashchange",listener);window.removeEventListener("popstate",listener)}}
function snapshot(){return window.location.hash}
function navigate(view:View,id=""){const hash=routeHash(view,id);if(window.location.hash!==hash){window.history.pushState(null,"",hash);window.dispatchEvent(new HashChangeEvent("hashchange"))}}
const navItems:[View,string,string][]=[["new","＋","新建任务"],["task","◫","工作台"],["materials","▤","资料库"],["artifacts","◇","成果库"]];
export default function Page(){
 const hash=useSyncExternalStore(subscribe,snapshot,()=>"");const route=parseRoute(hash);
 const [draft,setDraft]=useState<Draft>(emptyDraft);const [ready,setReady]=useState(false);const [error,setError]=useState("");const [busy,setBusy]=useState(false);const [source,setSource]=useState<Source|null>(null);const [revision,setRevision]=useState(0);const [artifactOffset,setArtifactOffset]=useState(0);const [menu,setMenu]=useState(false);
 const gate=useRef(createGate());const focusReply=useRef(false);const lastId=useRef("");
 const task=useApi(route.id&&["task","artifact"].includes(route.view)?`/tasks/${route.id}`:null,taskData,pollTask);
 const threads=useApi(`/task-threads?refresh=${revision}`,threadList,Boolean(task.data&&isActive(task.data.status)));
 const artifacts=useApi(route.view==="artifacts"?`/artifacts?offset=${artifactOffset}&limit=12&refresh=${revision}`:null,artifactList);
 useEffect(()=>{void Promise.resolve().then(()=>{try{setDraft(restoreDraft(localStorage.getItem(draftKey)));lastId.current=localStorage.getItem("qi-shu-task")||"";if(!window.location.hash&&lastId.current)navigate("task",lastId.current)}catch{setError("无法读取浏览器草稿；请检查本机浏览器存储设置")}setReady(true)})},[]);
 useEffect(()=>{if(task.data&&focusReply.current&&route.view==="task"){focusReply.current=false;requestAnimationFrame(()=>document.getElementById("correction")?.focus())}},[task.data,route.view]);
 useEffect(()=>{if(route.id){lastId.current=route.id;try{localStorage.setItem("qi-shu-task",route.id)}catch{}}},[route.id]);
 useEffect(()=>{if(menu){const before=document.activeElement as HTMLElement;document.querySelector<HTMLButtonElement>(".sidebar.is-open button")?.focus();return()=>before?.focus()}},[menu]);
 function navKeys(event:KeyboardEvent<HTMLElement>){if(!menu)return;if(event.key==="Escape"){event.preventDefault();setMenu(false)}if(event.key==="Tab"){const buttons=[...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")].filter(button=>button.offsetParent!==null);const first=buttons[0],last=buttons[buttons.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}}
 function saveDraft(next:Draft){setDraft(next);try{localStorage.setItem(draftKey,JSON.stringify(next));setError("")}catch{setError("草稿暂时无法保存到浏览器，请勿刷新；提交前请检查存储设置")}}
 function toggleSource(id:string){saveDraft({...draft,source_ids:draft.source_ids.includes(id)?draft.source_ids.filter(s=>s!==id):draft.source_ids.length<10?[...draft.source_ids,id]:draft.source_ids})}
 function uploaded(item:Source){if(draft.source_ids.length<10&&!draft.source_ids.includes(item.id))saveDraft({...draft,source_ids:[...draft.source_ids,item.id]})}
 function selectTask(id:string,reader=false,focus=false){lastId.current=id;focusReply.current=focus;try{localStorage.setItem("qi-shu-task",id)}catch{}setMenu(false);setError("");navigate(reader?"artifact":"task",id)}
 function go(view:View){setMenu(false);setError("");navigate(view,view==="task"?lastId.current:"")}
 async function submit(event:FormEvent){event.preventDefault();if(!ready||!draft.goal.trim()||!gate.current.enter())return;setBusy(true);setError("");
  try{
   let payload;
   try{payload=prepareSubmission(draft,localStorage.getItem(requestKey),()=>crypto.randomUUID());localStorage.setItem(draftKey,JSON.stringify(draft));localStorage.setItem(requestKey,JSON.stringify(payload))}catch{throw new Error("无法保存提交记录，尚未发送。请允许浏览器使用本地存储后再试")}
   const created=await request("/tasks",taskData,jsonBody(payload));
   selectTask(created.id);setRevision(v=>v+1);
   // Keep the submitted key for ambiguous retries; explicit clearing starts a new task.
  }catch(e){setError(e instanceof Error?e.message:"提交失败")}finally{gate.current.leave();setBusy(false)}
 }
 function clearDraft(){saveDraft({...emptyDraft,source_ids:[]});try{localStorage.removeItem(requestKey)}catch{} }
 const activeNav=route.view==="artifact"?"artifacts":route.view;
 return <main className="app-shell"><aside className={`sidebar${menu?" is-open":""}`} aria-label="主导航" role={menu?"dialog":undefined} aria-modal={menu||undefined} onKeyDown={navKeys}>
  <div className="brand"><span className="brand-symbol">枢</span><div>启枢 <small>你的 AI 工作伙伴</small></div><button type="button" className="mobile-close quiet" aria-label="关闭导航" onClick={()=>setMenu(false)}>×</button></div>
  <nav>{navItems.map(([view,icon,title])=><button type="button" className={`nav-item${activeNav===view?" active":""}`} key={view} onClick={()=>go(view)} aria-current={activeNav===view?"page":undefined}><span aria-hidden="true">{icon}</span>{title}</button>)}</nav>
  <div className="history-heading">最近任务 <button className="quiet" type="button" onClick={threads.reload} aria-label="刷新最近任务">↻</button></div><div className="history-list">{threads.loading&&!threads.data?<p className="note">正在读取…</p>:null}{threads.error&&<ErrorNotice message={threads.error} retry={threads.reload}/>} {threads.data?.length===0&&!threads.error&&<p className="note">从一个新任务开始。</p>}{threads.data?.map(item=><button type="button" className={`history-item${route.id===item.id?" selected":""}`} key={item.id} onClick={()=>selectTask(item.id)}><span>{shortTitle(item.goal,38)}</span><small>{labels[item.status]||item.status}</small></button>)}</div>
  <footer className="sidebar-footer"><span className="local-dot"/> 本机工作空间 <small>资料与成果保存在本机</small></footer>
 </aside>{menu&&<button className="nav-backdrop" aria-label="关闭导航" onClick={()=>setMenu(false)}/>}
 <div className="main-shell"><header className="topbar"><button type="button" className="mobile-menu" onClick={()=>setMenu(v=>!v)} aria-expanded={menu} aria-label="打开导航">☰</button><div className="breadcrumb">工作空间 <span>/</span> <strong>{route.view==="artifact"?"成果阅读":navItems.find(([v])=>v===route.view)?.[2]}</strong></div><span className="local-label">本机试用</span></header>
 {error&&<ErrorNotice message={error}/>}
 <div className={`main-content view-${route.view}`}>
 {route.view==="new"&&<div className="page-scroll"><div className="new-page"><span className="eyebrow">从一个清晰的目标开始</span><h1>今天，想一起完成什么？</h1><p className="intro">说说你的目标，附上资料。启枢会读取、梳理，再把成果交给你。</p><form className="task-form" onSubmit={submit}><label htmlFor="goal">交办目标</label><textarea id="goal" required maxLength={10000} disabled={!ready||busy} value={draft.goal} onChange={e=>saveDraft({...draft,goal:e.target.value})} placeholder="例如：根据客户访谈梳理需求，形成一份可讨论的建设方案。"/>
 <details className="paste-material"><summary>粘贴参考文字 / 读取 TXT、Markdown</summary><label htmlFor="material">参考文字</label><textarea id="material" maxLength={100000} value={draft.material} onChange={e=>saveDraft({...draft,material:e.target.value})}/><FileDrop material={draft.material} onLoad={text=>saveDraft({...draft,material:text})} onError={setError}/></details>
 <MaterialLibrary compact selected={draft.source_ids} onToggle={toggleSource} onPreview={setSource} onUploaded={uploaded}/>
 {draft.source_ids.length>0&&<div className="selected-sources"><span>已选 {draft.source_ids.length} 份</span>{draft.source_ids.map(id=><button type="button" key={id} title={`移除资料版本 ${id}`} onClick={()=>toggleSource(id)}>版本 {id.slice(0,8)} ×</button>)}</div>}
 <div className="form-footer"><p className="note">提交或修改会调用模型并产生费用，请使用虚构或脱敏资料。</p><div className="actions"><button type="button" disabled={busy} onClick={clearDraft}>清空并新建</button><button type="submit" className="primary" disabled={!ready||busy||!draft.goal.trim()}>{busy?"正在提交…":"交给启枢 →"}</button></div></div></form></div></div>}
 {route.view==="materials"&&<div className="page-scroll"><div className="page-heading"><span className="eyebrow">工作有据可依</span><h1>资料库</h1><p className="intro">把分散的材料放在一起，让每一次交办都有依据。</p></div><MaterialLibrary selected={draft.source_ids} onToggle={toggleSource} onPreview={setSource} onUploaded={uploaded}/>{draft.source_ids.length>0&&<div className="selection-footer"><span>已选 {draft.source_ids.length} 份资料</span><button className="primary" onClick={()=>go("new")}>带入新任务 →</button></div>}</div>}
 {route.view==="artifacts"&&<div className="page-scroll"><div className="page-heading"><span className="eyebrow">每一次推进，都留下成果</span><h1>成果库</h1><p className="intro">打开成果直接阅读。需要调整时，再回到对应任务继续。</p><button type="button" className="quiet" onClick={artifacts.reload}>刷新成果</button></div>{artifacts.error&&<ErrorNotice message={artifacts.error} retry={artifacts.reload}/>} {artifacts.loading?<p role="status">正在读取成果…</p>:artifacts.data?.length===0&&!artifacts.error?<div className="empty"><span className="empty-mark">◇</span><h2>还没有成果</h2><p>完成第一个任务后，文档会保存在这里。</p><button className="primary" onClick={()=>go("new")}>新建任务</button></div>:<div className="artifact-grid">{artifacts.data?.map(item=><article className="artifact-card" key={item.task_id}><span className="artifact-icon">{item.kind==="xlsx"?"▦":item.kind==="pptx"?"▣":"▤"}</span><span className="tag">{item.kind==="markdown"?"文档":item.kind.toUpperCase()}</span><h2>{shortTitle(item.title,80)}</h2><p>{item.sources.length} 份参考资料 · {item.created_at.slice(0,10)}</p><button type="button" className="secondary" onClick={()=>selectTask(item.task_id,true)}>打开成果 ↗</button></article>)}</div>}<div className="pagination"><button disabled={artifactOffset===0||artifacts.loading} onClick={()=>setArtifactOffset(v=>Math.max(0,v-12))}>上一页</button><span>第 {artifactOffset/12+1} 页</span><button disabled={artifacts.loading||!artifacts.data||artifacts.data.length<12} onClick={()=>setArtifactOffset(v=>v+12)}>下一页</button></div></div>}
 {["task","artifact"].includes(route.view)&&<>{task.error&&<ErrorNotice message={task.error} retry={task.reload}/>} {task.loading&&!task.data?<div className="empty" role="status">正在读取任务…</div>:task.data?<TaskView key={`${task.data.id}-${route.view}`} task={task.data} artifact={route.view==="artifact"} onPreview={setSource} onSelect={selectTask} onRefresh={task.reload} onBack={()=>go("artifacts")} onChanged={()=>setRevision(v=>v+1)}/>:!task.error&&<div className="empty"><span className="empty-mark">✦</span><h1>开始你的第一个任务</h1><p>从左侧选择最近任务，或交办一件新工作。</p><button className="primary" onClick={()=>go("new")}>新建任务 →</button></div>}</>}
 </div></div>{source&&<SourceDialog key={source.id} source={source} onClose={()=>setSource(null)}/>}</main>
}
