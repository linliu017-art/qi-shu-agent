import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Node's native TypeScript runner requires the file extension.
import {parseRoute,routeHash,prepareSubmission,restoreDraft,createGate} from '../app/lib/navigation.ts';
// @ts-expect-error Node's native TypeScript runner requires the file extension.
import {request,taskData,sourceList} from '../app/lib/client.ts';
test('成果深链接刷新仍在阅读视图，任务地址可独立分享',()=>{
 assert.deepEqual(parseRoute(routeHash('artifact','abc-123')),{view:'artifact',id:'abc-123'});
 assert.deepEqual(parseRoute('#task?task=abc-123'),{view:'task',id:'abc-123'});
 assert.deepEqual(parseRoute('#artifact?task=../../outside'),{view:'artifact',id:''});
 assert.equal(parseRoute('#unknown').view,'new');
});
test('超时刷新后同一载荷复用标识，修改附件生成新标识',()=>{
 const draft={goal:'整理',material:'文字',source_ids:['v1']};
 const first=prepareSubmission(draft,null,()=> 'first');
 assert.equal(prepareSubmission(restoreDraft(JSON.stringify(draft)),JSON.stringify(first),()=> 'second').client_request_id,'first');
 assert.equal(prepareSubmission({...draft,source_ids:['v2']},JSON.stringify(first),()=> 'second').client_request_id,'second');
});
test('同一事件循环双击只允许一次提交，失败释放后可重试',()=>{const gate=createGate();assert.equal(gate.enter(),true);assert.equal(gate.enter(),false);gate.leave();assert.equal(gate.enter(),true)});
test('无效浏览器草稿安全回退',()=>{assert.equal(restoreDraft('{bad').goal,'');assert.deepEqual(restoreDraft('{"goal":"a","material":"","source_ids":[4]}').source_ids,[])});
test('读取失败和格式错误不被当成空列表',async t=>{
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({error:{code:'CONFLICT',message:'版本已变化'}}),{status:409}));
 await assert.rejects(request('/tasks',taskData),/版本已变化/);
 assert.throws(()=>sourceList({}),/格式异常/);
 assert.throws(()=>taskData({id:'only-id'}),/格式异常/);
});
test('服务返回HTML显示错误并且不自动重试',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return new Response('<html>gateway</html>',{status:502})});
 await assert.rejects(request('/tasks',taskData),/有效数据/);assert.equal(calls,1);
});
test('网络失败提示提交状态不确定，不自动重发',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;throw new TypeError('network')});
 await assert.rejects(request('/tasks',taskData,{method:'POST'}),/可能已经保存/);assert.equal(calls,1);
});
