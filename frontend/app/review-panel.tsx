"use client";
import {useEffect, useState} from "react";

type Review = {status:"pending"|"confirmed"; items:string[]; revision:string; confirmed_at:string|null; can_confirm:boolean};
export default function ReviewPanel({id}:{id:string}) {
 const [review,setReview]=useState<Review|null>(null);
 const [error,setError]=useState("");
 const [saving,setSaving]=useState(false);
 useEffect(()=>{let active=true;fetch(`/api/v1/tasks/${id}`).then(async response=>{if(!response.ok)throw new Error("无法读取确认状态，请刷新重试");return response.json()}).then(data=>{if(active)setReview(data.review)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[id]);
 async function confirm(){
  if(!review)return;
  setSaving(true);setError("");
  try{
   const response=await fetch(`/api/v1/tasks/${id}/review/confirm`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:review.revision,confirm_all:true})});
   const data=await response.json();
   if(!response.ok)throw new Error(data.error?.message||"确认失败，请刷新重试");
   setReview(data);
  }catch(e){setError(e instanceof Error?e.message:"连接失败")}finally{setSaving(false)}
 }
 return <div className="draft-review" aria-label="草稿确认">
  <h3>{review?.status==="confirmed"?"当前版本已确认":"草稿待你确认"}</h3>
  {review?.status==="confirmed"?<p>已记录你的确认。后续修改将生成新的待确认版本。</p>:<>
   <p>生成完成不代表需求已经确认。请检查正文，并决定是否采纳下列建议。</p>
   {review?.items.length?<ol>{review.items.map((item,i)=><li key={i}>{item}</li>)}</ol>:<p className="note">没有单列建议；请检查正文中的假设和待确认信息。</p>}
   {review?.can_confirm?<><button type="button" className="secondary" disabled={saving} onClick={confirm}>{saving?"正在记录…":"确认当前草稿及以上建议"}</button><p className="note">仅记录当前版本的确认，不调用模型或执行对外操作。有不同意见，请在下方修改框说明。</p></>:review&&<p className="note">这个版本已有后续任务，请打开最新成果后确认。</p>}
  </>}
  {error&&<p className="error" role="alert">{error}</p>}
 </div>
}
