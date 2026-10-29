import json
import pytest
from app import agent, store, library


def test_citation_range_roundtrips_unicode():
    text = '甲乙🙂\n第二段'
    page = agent.cited_page(text, 2, 3)
    assert page['text'] == text[page['offset']:page['end_offset']] == '🙂\n第'
    assert page['source_kind'] == 'pasted'
    assert page['citation'] == '[粘贴资料，字符2–5，左闭右开]'
    assert page['next_offset'] == 5
    file_page = agent.cited_page(text, 0, 100, 'file-version-123')
    assert file_page['citation'] == f'[file-version-123，字符0–{len(text)}，左闭右开]'
    assert file_page['complete'] is True
    with pytest.raises(ValueError):
        agent.cited_page(text, 100, 2)


def test_pasted_material_must_be_read_before_requesting_it_again(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    store.init()
    task = store.create('生成验收清单', 'R1：空标题拒绝保存。')
    observed = []
    actions = [('ask_user', {'question':'请提供需求'}), ('read_material', {}),
               ('ask_user', {'question':'规则已读；请补充未给出的目标平台'})]
    class Response:
        def raise_for_status(self): pass
        def json(self):
            name, args = actions[len(observed)-1]
            return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(len(observed)), 'type':'function', 'function':{'name':name, 'arguments':json.dumps(args)}}]}}], 'usage':{'prompt_tokens':10, 'completion_tokens':10}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(json.loads(json.dumps(kwargs['json']['messages'])))
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    agent.run(task['id'])
    assert len(observed) == 3
    assert f'粘贴资料：{len(task["material"])}字符' in observed[0][1]['content']
    assert '先用read_material读取' in observed[1][-1]['content']
    page = json.loads(observed[2][-1]['content'])
    assert page['source_kind'] == 'pasted' and page['text'] == task['material']
    assert store.get(task['id'])['result'] == '规则已读；请补充未给出的目标平台'
    assert store.get(task['id'])['status'] == 'waiting'


def model_sequence(monkeypatch, actions):
    monkeypatch.setenv('MODEL_API_KEY', 'test-key')
    monkeypatch.setenv('MODEL_BASE_URL', 'https://example.test')
    monkeypatch.setenv('MODEL_NAME', 'test-model')
    observed = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            observed.append(json.loads(json.dumps(kwargs['json']['messages'])))
            name, args = actions[min(len(observed)-1, len(actions)-1)]
            class Response:
                def raise_for_status(self): pass
                def json(self):
                    return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(len(observed)), 'type':'function', 'function':{'name':name, 'arguments':json.dumps(args)}}]}}], 'usage':{'prompt_tokens':10, 'completion_tokens':10}}
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Client)
    return observed


def test_attached_file_is_read_before_asking(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    store.init()
    source = library.upload('需求.txt', '已有需求：集中查看。'.encode())
    task = store.create('生成需求', '', [source['id']])
    observed = model_sequence(monkeypatch, [
        ('ask_user', {'question':'请提供需求'}),
        ('read_source', {'source_id':source['id']}),
        ('ask_user', {'question':'请确认试点部门'}),
    ])
    agent.run(task['id'])
    assert '先用read_source读取' in observed[1][-1]['content']
    assert '集中查看' in observed[2][-1]['content']
    assert store.get(task['id'])['result'] == '请确认试点部门'
    assert store.get(task['id'])['status'] == 'waiting'


@pytest.mark.parametrize('tool,bad,good,expected', [
    ('ask_user', {'questions':[]}, {'question':'请确认范围'}, 'waiting'),
    ('save_artifact', {'content':''}, {'content':'草稿正文'}, 'completed'),
    ('plan_sections', {'titles':['只有一章']}, {'titles':['第一章','第二章']}, 'failed'),
])
def test_invalid_tool_arguments_get_feedback_and_can_be_corrected(tmp_path, monkeypatch, tool, bad, good, expected):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    store.init()
    task=store.create('测试','')
    actions=[(tool,bad),(tool,good)]
    if tool == 'plan_sections':
        actions += [('save_section', {'position':1,'content':'正文一'}), ('save_section', {'position':2,'content':'正文二'})]
        expected = 'completed'
    observed=model_sequence(monkeypatch, actions)
    agent.run(task['id'])
    assert '参数不符合要求' in observed[1][-1]['content']
    assert observed[1][-2]['tool_calls'][0]['function']['arguments'] == '{}'
    assert store.get(task['id'])['status'] == expected


def test_repeated_invalid_arguments_stop_at_step_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'test.sqlite'))
    store.init()
    task=store.create('测试','')
    observed=model_sequence(monkeypatch, [('ask_user', {'questions':[]})])
    agent.run(task['id'])
    assert len(observed) == 16
    assert store.get(task['id'])['status'] == 'failed'
    assert '步数上限' in store.get(task['id'])['progress']
