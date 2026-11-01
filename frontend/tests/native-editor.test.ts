import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node's native TypeScript runner requires the file extension.
import {editorCapability,editorDecision,editorSession,editorStatus} from '../app/lib/native-editor.ts';

const sid='a'.repeat(32);
const session=(origin:string)=>({session_id:sid,editor_origin:origin,config:{document:{key:sid},token:'test-token'}});

test('native editor only accepts a signed session for a local editor',()=>{
 assert.equal(editorSession(session('http://127.0.0.1:18080')).session_id,sid);
 for(const origin of ['https://example.com','http://127.0.0.1.evil.test','http://user@localhost','javascript:alert(1)'])assert.throws(()=>editorSession(session(origin)));
 assert.throws(()=>editorSession({...session('http://localhost:18080'),config:{document:{key:'wrong'},token:'x'}}));
 assert.deepEqual(editorCapability({enabled:false}),{enabled:false});
});

test('native editor keeps review and conflict states distinct',()=>{
 assert.deepEqual(editorStatus({status:'review_required',task_id:null,can_recover:true,warnings:['图片可能变化']}),{status:'review_required',task_id:null,can_recover:true,warnings:['图片可能变化']});
 assert.deepEqual(editorDecision({status:'conflict',task_id:null}),{status:'conflict',task_id:null});
 assert.throws(()=>editorStatus({status:'saved',task_id:null,can_recover:true,warnings:'bad'}));
});
