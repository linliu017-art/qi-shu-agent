export type EditorSession={session_id:string;editor_origin:string;config:Record<string,unknown>};
export type EditorStatus={status:string;task_id:string|null;can_recover:boolean;warnings:string[]};
function object(value:unknown):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('编辑器返回格式异常');return value as Record<string,unknown>}
export function editorCapability(value:unknown):{enabled:boolean}{const data=object(value);if(typeof data.enabled!=='boolean')throw new Error('编辑器状态异常');return {enabled:data.enabled}}
export function editorSession(value:unknown):EditorSession{
 const data=object(value);if(typeof data.session_id!=='string'||!/^[a-f0-9]{32}$/.test(data.session_id)||typeof data.editor_origin!=='string')throw new Error('编辑器配置异常');
 let origin:URL;try{origin=new URL(data.editor_origin)}catch{throw new Error('编辑器地址异常')}
 if(!['http:','https:'].includes(origin.protocol)||!['127.0.0.1','localhost','[::1]'].includes(origin.hostname)||origin.origin!==data.editor_origin||origin.username||origin.password)throw new Error('编辑器地址必须为本机服务');
 const config=object(data.config),document=object(config.document);if(document.key!==data.session_id||typeof config.token!=='string')throw new Error('编辑器会话异常');
 return {session_id:data.session_id,editor_origin:data.editor_origin,config};
}
export function editorStatus(value:unknown):EditorStatus{
 const data=object(value);if(typeof data.status!=='string'||!(typeof data.task_id==='string'||data.task_id===null)||typeof data.can_recover!=='boolean'||!Array.isArray(data.warnings)||!data.warnings.every(v=>typeof v==='string'))throw new Error('编辑保存状态异常');
 return {status:data.status,task_id:data.task_id,can_recover:data.can_recover,warnings:data.warnings as string[]};
}

export function editorDecision(value:unknown):{status:string;task_id:string|null}{const data=object(value);if(typeof data.status!=="string"||!(typeof data.task_id==="string"||data.task_id===null))throw new Error("编辑保存结果异常");return {status:data.status,task_id:data.task_id}}
