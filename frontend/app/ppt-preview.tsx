"use client";
import {useEffect,useRef,useState} from 'react';
import {pptPreviewData,pptBodyFontSize,slidePage,type Slide} from './lib/office';
import {useApi} from './lib/use-api';
import {ErrorNotice} from './materials';

function SlideCanvas({slide,index}:{slide:Slide;index:number}){
 const bodyClass=pptBodyFontSize(slide)===18?'normal':'compact';
 return <div className="ppt-slide" aria-label={`第 ${index+1} 页：${slide.title}`}>
  <h2 className="ppt-slide-title">{slide.title}</h2>
  <div className={`ppt-slide-body ${bodyClass}`}>{slide.body.map((line,i)=><p key={i}>• {line}</p>)}</div>
  <span className="ppt-slide-number" aria-hidden="true">{index+1}</span>
 </div>
}
function ZoomDialog({slide,index,total,onMove,onClose}:{slide:Slide;index:number;total:number;onMove:(delta:number)=>void;onClose:()=>void}){
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[]);
 return <dialog ref={ref} className="ppt-zoom-dialog" aria-labelledby="ppt-zoom-title" onClose={onClose}>
  <header className="ppt-zoom-header"><div><span className="eyebrow">幻灯片预览</span><h2 id="ppt-zoom-title">{slide.title}</h2></div><button type="button" autoFocus onClick={onClose}>关闭</button></header>
  <div className="ppt-zoom-body"><div className="ppt-zoom-canvas"><SlideCanvas slide={slide} index={index}/></div></div>
  <footer className="ppt-zoom-footer"><button type="button" disabled={index===0} onClick={()=>onMove(-1)}>← 上一页</button><span aria-live="polite">第 {index+1} / {total} 页</span><button type="button" disabled={index===total-1} onClick={()=>onMove(1)}>下一页 →</button></footer>
 </dialog>
}
export default function PptPreview({id}:{id:string}){
 const [page,setPage]=useState(0);const [zoom,setZoom]=useState(false);const resource=useApi(`/tasks/${encodeURIComponent(id)}/office`,pptPreviewData);
 if(resource.error)return <ErrorNotice message={`无法加载幻灯片：${resource.error}`} retry={resource.reload}/>;
 if(resource.loading||!resource.data)return <p role="status" className="loading">正在加载幻灯片…</p>;
 const slides=resource.data.slides;const selected=Math.min(page,slides.length-1);const slide=slides[selected];
 if(!slide)return <div className="empty compact"><p>没有可预览的幻灯片。</p></div>;
 function move(delta:number){setPage(slidePage(selected,delta,slides.length))}
 return <section className="ppt-preview" aria-label="PPT幻灯片预览">
  <div className="ppt-slide-viewport"><SlideCanvas slide={slide} index={selected}/></div>
  <div className="ppt-controls"><button type="button" disabled={selected===0} onClick={()=>move(-1)}>← 上一页</button><span aria-live="polite">第 {selected+1} / {slides.length} 页</span><button type="button" disabled={selected===slides.length-1} onClick={()=>move(1)}>下一页 →</button><button type="button" onClick={()=>setZoom(true)}>放大查看</button></div>
  <p className="note ppt-preview-note">按照生成的 PPT 模板展示，字体和换行以下载文件为准。</p>
  {zoom&&<ZoomDialog slide={slide} index={selected} total={slides.length} onMove={move} onClose={()=>setZoom(false)}/>}
 </section>
}
