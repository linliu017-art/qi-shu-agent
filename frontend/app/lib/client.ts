export type Source = {id:string; name:string; kind:string; sha256:string; parent_id:string|null; created_at:string};
export type Task = {id:string; goal:string; original_goal?:string; material:string; status:string; progress:string; result:string; artifact_kind?:string; native_office?:boolean; sources?:Source[]; draft?:{position:number;title:string;content:string|null}[]|null; usage?:{input_tokens:number;output_tokens:number}; cache_usage?:{calls:number;reported_calls:number;hit_tokens:number|null;miss_tokens:number|null}};
export type Summary = {id:string;goal:string;status:string};
export type Artifact = {task_id:string;title:string;kind:string;created_at:string;sources:Source[];version?:number;version_count?:number};
export type Preview = Source & {text:string;offset:number;next_offset:number|null;total_characters:number};
export const labels:Record<string,string>={queued:"等待执行",running:"执行中",completed:"生成已完成",failed:"未完成",cancelled:"已停止",interrupted:"已中断",waiting:"等待补充"};
export const isActive=(status:string)=>["queued","running"].includes(status);
export function shortTitle(goal:string,limit=90){
  let title=goal;
  if(goal.startsWith("原任务：")&&(goal.includes("\n已有成果：")||goal.includes("\n待答问题："))) title=goal.slice(4).split(/\n已有成果：|\n待答问题：/)[0];
  title=title.replace(/\s+/g," ").trim();
  return title.length>limit?title.slice(0,limit)+"…":title;
}
function record(value:unknown):Record<string,unknown>{if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("服务返回格式异常，请刷新重试");return value as Record<string,unknown>}
function fields(value:unknown, keys:string[]){const row=record(value);if(keys.some(key=>typeof row[key]!=="string"))throw new Error("服务返回格式异常，请刷新重试");return row}
export function taskData(value:unknown):Task {const row=fields(value,["id","goal","material","status","progress","result"]);if(row.sources!==undefined)sourceList({materials:row.sources});return row as Task}
export function sourceData(value:unknown):Source{return fields(value,["id","name","kind","sha256","created_at"]) as Source}
export function sourceList(value:unknown):Source[]{const rows=record(value).materials;if(!Array.isArray(rows))throw new Error("资料列表格式异常");return rows.map(sourceData)}
export function threadList(value:unknown):Summary[]{const rows=record(value).tasks;if(!Array.isArray(rows))throw new Error("任务列表格式异常");return rows.map(v=>fields(v,["id","goal","status"]) as Summary)}
export function artifactList(value:unknown):Artifact[]{const rows=record(value).artifacts;if(!Array.isArray(rows))throw new Error("成果列表格式异常");return rows.map(v=>{const row=fields(v,["task_id","title","kind","created_at"]);sourceList({materials:row.sources});return row as Artifact})}
export function previewData(value:unknown):Preview {const row=fields(value,["text"]);sourceData(value);if(typeof row.offset!=="number"||typeof row.total_characters!=="number"||!(row.next_offset===null||typeof row.next_offset==="number"))throw new Error("资料页码格式异常");return row as Preview}
export class ApiError extends Error {status:number; constructor(message:string,status=0){super(message);this.status=status}}
export async function request<T>(path:string,decode:(value:unknown)=>T,init:RequestInit={},timeout=20000):Promise<T>{
  const signal=AbortSignal.any([AbortSignal.timeout(timeout),...(init.signal?[init.signal]:[])]);
  let response:Response;
  try {response=await fetch(`/api/v1${path}`,{...init,signal,cache:"no-store"})}catch(error){if(init.signal?.aborted)throw error;throw new ApiError(init.method&&init.method!=="GET"?(path==="/tasks"?"连接中断或超时，提交中的任务可能已经保存；保留当前内容重试可找回同一次创建":"连接中断或超时，操作可能已经保存；请先核对任务状态"):"连接中断或超时，请稍后重试读取")}
  let data:unknown;
  try{data=await response.json()}catch{throw new ApiError("服务没有返回有效数据，请稍后重试",response.status)}
  if(!response.ok){const problem=record(data).error;throw new ApiError(problem&&typeof problem==="object"&&"message" in problem&&typeof problem.message==="string"?problem.message:"请求失败，请稍后重试",response.status)}
  return decode(data);
}
export const jsonBody=(value:unknown):RequestInit=>({method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(value)});
export function correctionData(value:unknown):{task?:Task;message?:string}{const row=record(value);if(row.task)return {task:taskData(row.task)};if(typeof row.message==="string")return {message:row.message};throw new Error("未能确认补充结果，请回查任务")}

export const pollTask=(task:Task)=>isActive(task.status);

export function documentTitle(task:Task){const heading=task.result.match(/^#\s+(.+)$/m)?.[1];return shortTitle(heading||task.original_goal||task.goal,100)}
