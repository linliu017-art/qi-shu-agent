export type View="new"|"task"|"materials"|"artifacts"|"artifact";
export type Route={view:View;id:string};
export function parseRoute(hash:string):Route{
 const parts=hash.replace(/^#/,"").split("?");const view=parts[0];
 const id=new URLSearchParams(parts[1]||"").get("task")||"";
 if(!["new","task","materials","artifacts","artifact"].includes(view))return {view:"new",id:""};
 return {view:view as View,id:/^[a-zA-Z0-9_-]{1,64}$/.test(id)?id:""};
}
export function routeHash(view:View,id=""){return `#${view}${id?`?task=${encodeURIComponent(id)}`:""}`}
export type Draft={goal:string;material:string;source_ids:string[]};
export type Submission=Draft & {client_request_id:string};
export const emptyDraft:Draft={goal:"",material:"",source_ids:[]};
export function restoreDraft(value:string|null):Draft{
 try{const row=JSON.parse(value||"null");if(row&&typeof row.goal==="string"&&typeof row.material==="string"&&Array.isArray(row.source_ids)&&row.source_ids.length<=10&&row.source_ids.every((v:unknown)=>typeof v==="string"))return {goal:row.goal,material:row.material,source_ids:row.source_ids}}catch{}
 return emptyDraft;
}
export function prepareSubmission(draft:Draft,saved:string|null,newId:()=>string):Submission{
 try{const old=JSON.parse(saved||"null");if(old&&typeof old.client_request_id==="string"&&old.goal===draft.goal&&old.material===draft.material&&JSON.stringify(old.source_ids)===JSON.stringify(draft.source_ids))return {...draft,client_request_id:old.client_request_id}}catch{}
 return {...draft,client_request_id:newId()};
}
export function createGate(){let locked=false;return {enter(){if(locked)return false;locked=true;return true},leave(){locked=false}}}
