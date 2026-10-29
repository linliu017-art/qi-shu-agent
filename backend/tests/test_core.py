import json
from fastapi.testclient import TestClient
from app import store, agent
from app.main import app


def test_save_cancel_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    task = store.create('目标', '资料')
    assert store.update(task['id'], 'running', '进行中')
    assert store.cancel(task['id'])
    assert not store.update(task['id'], 'completed', '完成', '不可保存')
    assert store.get(task['id'])['result'] == ''
    task2 = store.create('另一个目标', '资料')
    store.init()
    assert store.get(task2['id'])['status'] == 'interrupted'


def test_api_errors_and_task(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    with TestClient(app) as client:
        assert client.post('/api/v1/tasks', json={'goal': ''}).json()['error']['code'] == 'INVALID_INPUT'
        assert client.get('/api/v1/tasks/missing').json()['error']['code'] == 'NOT_FOUND'
        response = client.post('/api/v1/tasks', json={'goal': '整理', 'material': '样例'})
        assert response.status_code == 201
        tid = response.json()['id']
        assert client.get('/api/v1/tasks/' + tid).json()['material'] == '样例'


def test_agent_calls_read_and_saves_result(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('整理需求', '虚构资料')
    observed = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            if len(observed) == 1:
                call = {'id': 'c1', 'type': 'function', 'function': {'name': 'read_material', 'arguments': '{}'}}
            else:
                call = {'id': 'c2', 'type': 'function', 'function': {'name': 'save_artifact', 'arguments': json.dumps({'content': '依据资料的成果'})}}
            return {'choices': [{'message': {'role': 'assistant', 'tool_calls': [call]}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(kwargs['json']['messages'][:])
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    saved = store.get(task['id'])
    assert saved['status'] == 'completed'
    assert saved['result'] == '依据资料的成果'
    assert store.task_usage(task['id']) == {'input_tokens': 20, 'output_tokens': 20}
    assert json.loads(observed[1][-1]['content'])['text'] == '虚构资料'


def test_correction_survives_and_blocks_stale_completion(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    task = store.create('目标', '资料')
    store.update(task['id'], 'running', '处理中')
    assert store.add_correction(task['id'], '请补充风险')
    assert not store.finish(task['id'], '未处理补充的结果', 0)
    corrections = store.corrections_since(task['id'], 0)
    assert corrections[0]['content'] == '请补充风险'
    assert store.finish(task['id'], '已考虑风险', corrections[0]['id'])
    assert not store.add_correction(task['id'], '无法修改已完成任务')


def test_history_and_correction_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    with TestClient(app) as client:
        task = store.create('已有任务', '材料')
        assert any(t['id'] == task['id'] for t in client.get('/api/v1/tasks').json()['tasks'])
        r = client.post(f"/api/v1/tasks/{task['id']}/corrections", json={'content':'请补充结论'})
        assert r.status_code == 201
        assert store.corrections_since(task['id'], 0)[0]['content'] == '请补充结论'
        assert client.post('/api/v1/tasks/notfound/corrections', json={'content':'补充'}).status_code == 404


def test_no_model_does_not_produce_fake_result(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    store.init()
    task = store.create('任务', '资料')
    agent.run(task['id'])
    result = store.get(task['id'])
    assert result['status'] == 'failed'
    assert result['result'] == ''
    assert '模型未配置' in result['progress']


def test_invalid_tool_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('任务', '资料')
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':'c1','type':'function','function':{'name':'execute_shell','arguments':'{}'}}]}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs): return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status'] == 'failed'
    assert store.get(task['id'])['result'] == ''


def test_ask_user_saves_question_and_can_continue(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('写方案', '')
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':'c1','type':'function','function':{'name':'ask_user','arguments':json.dumps({'question':'请提供项目背景'})}}]}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs): return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status'] == 'waiting'
    assert store.get(task['id'])['result'] == '请提供项目背景'
    with TestClient(app) as client:
        monkeypatch.setattr('app.main.pool.submit', lambda *args: None)
        response = client.post(f"/api/v1/tasks/{task['id']}/corrections", json={'content':'虚构背景'})
        assert response.status_code == 201
        new_task = response.json()['task']
        assert '虚构背景' in new_task['goal']
        assert store.context_link(new_task['id'])['parent_id'] == task['id']
        assert store.get(task['id'])['result'] == '请提供项目背景'


def test_oversized_context_stops_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('目标' * 30000, '资料')
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): raise AssertionError('超过限制不得发出请求')
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status'] == 'failed'
    assert '用量限制' in store.get(task['id'])['progress']


def test_truncated_model_output_is_accounted_and_reported(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('写方案', '资料')
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'finish_reason':'length','message':{'role':'assistant','tool_calls':[]}}], 'usage':{'prompt_tokens':100,'completion_tokens':8192}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs): return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status'] == 'failed'
    assert '长度限制' in store.get(task['id'])['progress']
    assert store.task_usage(task['id']) == {'input_tokens':100,'output_tokens':8192}


def test_followup_preserves_versions_without_embedding_document(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    original = store.create('写方案', '虚构资料')
    store.update(original['id'], 'running', '处理中')
    original_text = '原始成果内容' * 5000
    assert store.finish(original['id'], original_text, 0)
    followup = store.create_followup(original['id'], '改进结尾')
    assert followup['goal'] == '改进结尾'
    assert len(followup['goal']) < 100
    assert store.get(original['id'])['result'] == original_text
    assert store.original_goal(followup['id']) == '写方案'
    assert store.context_link(followup['id'])['parent_id'] == original['id']


def test_paging_keeps_entire_content_and_rejects_out_of_bounds():
    text = '甲乙丙' * 2000
    first = json.loads(agent.page_text(text, 0, 3000))
    second = json.loads(agent.page_text(text, first['next_offset'], 3000))
    assert first['complete'] is False
    assert second['complete'] is True
    assert first['text'] + second['text'] == text
    try:
        agent.page_text(text, len(text) + 1, 100)
    except ValueError:
        pass
    else:
        raise AssertionError('越界读取应失败')


def test_compaction_keeps_user_corrections_and_complete_recent_exchanges():
    messages = [{'role':'system','content':'规则'}, {'role':'user','content':'原目标'}]
    for i in range(4):
        messages.extend([{'role':'assistant','tool_calls':[{'id':str(i)}]}, {'role':'tool','tool_call_id':str(i),'content':f'片段{i}'}])
        if i == 0:
            messages.append({'role':'user','content':'补充要求'})
    compact = agent.compact_messages(messages)
    assert [m.get('content') for m in compact if m['role']=='user'] == ['原目标','补充要求']
    assert [m['tool_call_id'] for m in compact if m['role']=='tool'] == ['2','3']
    assert [m['tool_calls'][0]['id'] for m in compact if m['role']=='assistant'] == ['2','3']


def test_model_reads_previous_result_on_demand(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    original = store.create('写方案', '资料')
    store.update(original['id'], 'running', '处理中')
    assert store.finish(original['id'], '之前的成果', 0)
    followup = store.create_followup(original['id'], '更新结尾')
    observed = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            if len(observed) == 1:
                call={'id':'c1','type':'function','function':{'name':'read_previous_result','arguments':'{}'}}
            else:
                call={'id':'c2','type':'function','function':{'name':'save_artifact','arguments':json.dumps({'content':'修改后成果'})}}
            return {'choices':[{'message':{'role':'assistant','tool_calls':[call]}}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(kwargs['json']['messages'][:])
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(followup['id'])
    assert '之前的成果' not in observed[0][1]['content']
    assert json.loads(observed[1][-1]['content'])['text'] == '之前的成果'
    assert store.get(followup['id'])['result'] == '修改后成果'
    assert store.get(original['id'])['result'] == '之前的成果'


def test_precise_edits_preserve_unmodified_text_and_reject_ambiguity():
    original = '# 前言\n不变的内容\n# 结尾\n旧结论\n# 附录\n不要改动'
    edits = [agent.Edit(original='旧结论', replacement='新结论')]
    assert agent.apply_exact_edits(original, edits) == original.replace('旧结论', '新结论')
    for text, bad_edits in [
        ('重复 内容 重复', [agent.Edit(original='重复', replacement='更新')]),
        ('原始内容', [agent.Edit(original='不存在', replacement='更新')]),
        ('abcdef', [agent.Edit(original='bcd', replacement='x'), agent.Edit(original='cde', replacement='y')]),
    ]:
        try:
            agent.apply_exact_edits(text, bad_edits)
        except ValueError:
            pass
        else:
            raise AssertionError('不明确或重叠的编辑不得执行')


def test_long_followup_cannot_replace_entire_document_after_partial_read(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    original = store.create('写方案', '资料')
    store.update(original['id'], 'running', '处理中')
    content = '前文' * 2000 + '\n独有的结尾\n' + '附录' * 2000
    assert store.finish(original['id'], content, 0)
    followup = store.create_followup(original['id'], '修改结尾')
    calls = [
        {'id':'a','type':'function','function':{'name':'read_previous_result','arguments':'{}'}},
        {'id':'b','type':'function','function':{'name':'save_artifact','arguments':json.dumps({'content':'截断的短文'})}},
        {'id':'c','type':'function','function':{'name':'read_previous_result','arguments':json.dumps({'offset':3990})}},
        {'id':'d','type':'function','function':{'name':'apply_edits','arguments':json.dumps({'edits':[{'original':'独有的结尾','replacement':'新结尾'}]})}},
    ]
    observed=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'role':'assistant','tool_calls':[calls[len(observed)-1]]}}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(kwargs['json']['messages'][:])
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(followup['id'])
    assert '未完整读取' in observed[2][-1]['content']
    assert store.get(original['id'])['result'] == content
    assert store.get(followup['id'])['result'] == content.replace('独有的结尾','新结尾')


def test_cache_usage_tracks_reported_and_unknown_separately(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    task = store.create('任务', '资料')
    store.record_usage(task['id'], 100, 25, 80, 20)
    store.record_usage(task['id'], 40, 10)
    assert store.task_usage(task['id']) == {'input_tokens': 140, 'output_tokens': 35}
    assert store.task_cache_usage(task['id']) == {'calls':2, 'reported_calls':1, 'hit_tokens':80, 'miss_tokens':20}
    store.init()
    assert store.task_cache_usage(task['id'])['hit_tokens'] == 80
    assert store.task_cache_usage('missing')['hit_tokens'] is None


def test_cache_usage_missing_or_inconsistent_is_unknown():
    assert agent.cache_breakdown(agent.ModelUsage(prompt_tokens=100, completion_tokens=1)) == (None, None)
    assert agent.cache_breakdown(agent.ModelUsage(prompt_tokens=100, completion_tokens=1, prompt_cache_hit_tokens=80, prompt_cache_miss_tokens=20)) == (80, 20)
    assert agent.cache_breakdown(agent.ModelUsage(prompt_tokens=100, completion_tokens=1, prompt_cache_hit_tokens=90, prompt_cache_miss_tokens=20)) == (None, None)


def test_small_tool_exchanges_keep_prefix_and_record_cache_usage(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('根据资料整理', '虚构资料')
    observed = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            n = len(observed)
            name = 'read_material' if n < 4 else 'save_artifact'
            args = '{}' if n < 4 else json.dumps({'content':'成果'})
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(n),'type':'function','function':{'name':name,'arguments':args}}]}}], 'usage':{'prompt_tokens':100,'completion_tokens':10,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(json.loads(json.dumps(kwargs['json']['messages'])))
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status'] == 'completed'
    for previous, following in zip(observed, observed[1:]):
        assert following[:len(previous)] == previous
    assert store.task_cache_usage(task['id']) == {'calls':4,'reported_calls':4,'hit_tokens':320,'miss_tokens':80}


def test_draft_checkpoint_guards_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    task = store.create('长报告', '资料')
    store.update(task['id'], 'running', '处理中')
    assert store.draft_write(task['id'], 'plan', 0, titles=['背景','建议']) is None
    assert store.draft_write(task['id'], 'section', 0, position=1, content='第一段') is None
    assert store.draft_write(task['id'], 'section', 0, position=1, content='第一段') is None
    assert '不能静默覆盖' in store.draft_write(task['id'], 'section', 0, position=1, content='替换第一段')
    assert '尚未全部保存' in store.draft_write(task['id'], 'finish', 0)
    store.init()
    assert store.get(task['id'])['status'] == 'interrupted'
    assert store.draft(task['id'])[0]['content'] == '第一段'
    assert store.resume(task['id'])
    assert not store.resume(task['id'])
    store.update(task['id'], 'running', '继续')
    assert store.draft_write(task['id'], 'section', 0, position=2, content='第二段') is None
    assert store.draft_write(task['id'], 'finish', 0) is None
    assert store.get(task['id'])['result'] == '## 背景\n\n第一段\n\n## 建议\n\n第二段'


def test_pending_correction_and_cancel_block_draft_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    store.init()
    task = store.create('任务', '')
    store.update(task['id'], 'running', '处理中')
    assert store.draft_write(task['id'], 'plan', 0, titles=['一','二']) is None
    assert store.add_correction(task['id'], '修改范围')
    assert '新的补充' in store.draft_write(task['id'], 'section', 0, position=1, content='内容')
    correction_id = store.corrections_since(task['id'], 0)[0]['id']
    assert store.draft_write(task['id'], 'section', correction_id, position=1, content='内容') is None
    assert store.cancel(task['id'])
    assert '停止' in store.draft_write(task['id'], 'section', correction_id, position=2, content='内容')


def test_agent_resumes_partial_draft_after_model_failure(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task=store.create('写长报告','虚构资料')
    calls=[
        ('plan_sections',{'titles':['背景','建议']}),
        ('save_section',{'position':1,'content':'已保存的背景'}),
        ('save_section',{'position':2,'content':'恢复后的建议'}),
        ('finish_sections',{}),
    ]
    state={'count':0,'fail':True,'resumed_context':''}
    class Response:
        def __init__(self,index): self.index=index
        def raise_for_status(self): pass
        def json(self):
            name,args=calls[self.index]
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(self.index),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],'usage':{'prompt_tokens':10,'completion_tokens':10}}
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs):
            if state['count']==2 and state['fail']:
                state['fail']=False
                raise httpx.ReadTimeout('timeout')
            if state['count']==2:
                state['resumed_context']=kwargs['json']['messages'][1]['content']
            n=state['count']; state['count']+=1
            return Response(n)
    monkeypatch.setattr(agent.httpx,'Client',Client)
    agent.run(task['id'])
    assert store.get(task['id'])['status']=='failed'
    assert store.draft(task['id'])[0]['content']=='已保存的背景'
    assert store.resume(task['id'])
    agent.run(task['id'])
    assert store.get(task['id'])['status']=='completed'
    assert '已保存的背景' in store.get(task['id'])['result']
    assert '恢复后的建议' in store.get(task['id'])['result']
    assert '"saved": true' in state['resumed_context']
    assert store.task_usage(task['id']) == {'input_tokens':30,'output_tokens':30}


def test_complete_saved_draft_merges_without_another_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    store.init()
    task=store.create('长报告','资料')
    store.update(task['id'],'running','处理中')
    store.draft_write(task['id'],'plan',0,titles=['一','二'])
    store.draft_write(task['id'],'section',0,position=1,content='一段')
    store.draft_write(task['id'],'section',0,position=2,content='二段')
    store.update(task['id'],'failed','中断')
    assert store.resume(task['id'])
    agent.run(task['id'])
    assert store.get(task['id'])['status']=='completed'
    assert store.get(task['id'])['result']=='## 一\n\n一段\n\n## 二\n\n二段'
    assert store.task_usage(task['id']) == {'input_tokens':0,'output_tokens':0}


def test_merge_does_not_repeat_existing_heading():
    assert store.assemble_section('第一章 背景','## 第一章 背景\n\n正文') == '## 第一章 背景\n\n正文'
    assert store.assemble_section('第一章 背景','正文') == '## 第一章 背景\n\n正文'


def test_missing_previous_result_is_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init(); task=store.create('写方案','资料')
    observed=[]
    class Response:
        def raise_for_status(self): pass
        def json(self):
            if len(observed)==1:
                call={'id':'a','type':'function','function':{'name':'read_previous_result','arguments':'{}'}}
            else:
                call={'id':'b','type':'function','function':{'name':'save_artifact','arguments':json.dumps({'content':'成果'})}}
            return {'choices':[{'message':{'role':'assistant','tool_calls':[call]}}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs):
            observed.append(kwargs['json']['messages'][:]);return Response()
    monkeypatch.setattr(agent.httpx,'Client',Client)
    agent.run(task['id'])
    assert '没有上一版成果' in observed[1][-1]['content']
    assert store.get(task['id'])['status']=='completed'


def test_oversized_section_is_reported_and_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY','test-key'); monkeypatch.setenv('MODEL_BASE_URL','https://example.test'); monkeypatch.setenv('MODEL_NAME','test-model')
    store.init();task=store.create('写报告','资料');observed=[]
    calls=[('plan_sections',{'titles':['背景','建议']}),('save_section',{'position':1,'content':'超'*7001}),('save_section',{'position':1,'content':'精简背景'}),('save_section',{'position':2,'content':'建议'})]
    class Response:
        def raise_for_status(self): pass
        def json(self):
            name,args=calls[len(observed)-1]
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(len(observed)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs): observed.append(kwargs['json']['messages'][:]); return Response()
    monkeypatch.setattr(agent.httpx,'Client',Client)
    agent.run(task['id'])
    assert '7000' in observed[2][-1]['content']
    assert store.get(task['id'])['status']=='completed'
    assert '精简背景' in store.get(task['id'])['result']


def test_long_document_parts_combine_without_loss(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    store.init(); task=store.create('长文','资料'); store.update(task['id'],'running','处理中')
    sections=['甲'*6000,'乙'*6000,'丙'*6000]
    assert store.draft_write(task['id'],'plan',0,titles=['一','二','三']) is None
    for index,content in enumerate(sections,1):
        assert store.draft_write(task['id'],'section',0,position=index,content=content) is None
    assert store.draft_write(task['id'],'finish',0) is None
    merged=store.get(task['id'])['result']
    assert all(s in merged for s in sections)
    assert len(merged)>18000
