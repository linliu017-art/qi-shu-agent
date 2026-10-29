import json
import pytest
from fastapi.testclient import TestClient
from app import store, review, agent, library
from app.main import app
from app.office import OfficeDocument

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'review.sqlite'))
    store.init()


def completed(items=None):
    task=store.create('草稿', '虚构资料')
    store.update(task['id'],'running','处理中')
    assert store.finish(task['id'],'草稿正文',0,items)
    return task['id']


def test_review_confirmation_is_explicit_idempotent_and_persistent(db):
    tid=completed(['建议只读'])
    initial=review.get(tid)
    assert initial['status']=='pending' and initial['can_confirm']
    final=review.confirm(tid,initial['revision'])
    assert final['status']=='confirmed'
    assert review.confirm(tid,initial['revision'])==final
    store.init()
    assert review.get(tid)==final
    child=store.create_followup(tid,'改标题')
    assert review.get(child['id'])['status']=='pending'
    assert review.get(child['id'])['items']==[]  # accepted choices live in history, not pending again
    assert store.task_history(child['id'])[0]['review']['status']=='confirmed'
    assert review.get(tid)['status']=='confirmed'
    with pytest.raises(ValueError): review.confirm(tid,initial['revision'])


def test_unconfirmed_items_inherit_without_false_confirmation(db):
    tid=completed(['建议筛选'])
    child=store.create_followup(tid,'可以')
    assert review.get(child['id'])['status']=='pending'
    assert review.get(child['id'])['items']==['建议筛选']
    assert review.get(tid)['status']=='pending'


def test_confirm_api_rejects_stale_wrong_owner_and_incomplete(db):
    tid=completed(['建议筛选']); initial=review.get(tid)
    with TestClient(app) as client:
        assert client.post(f'/api/v1/tasks/{tid}/review/confirm',json={'expected_revision':initial['revision'],'confirm_all':False}).status_code==422
        assert client.post(f'/api/v1/tasks/{tid}/review/confirm',json={'expected_revision':'0'*64,'confirm_all':True}).status_code==409
        assert client.post(f'/api/v1/tasks/{tid}/review/confirm',json={'expected_revision':initial['revision'],'confirm_all':True}).json()['status']=='confirmed'
        waiting=store.create('待问','')['id']
        assert client.post(f'/api/v1/tasks/{waiting}/review/confirm',json={'expected_revision':review.get(waiting)['revision'],'confirm_all':True}).status_code==409
        with store.connection() as conn: conn.execute("UPDATE tasks SET owner_id='other' WHERE id=?",(tid,))
        assert client.post(f'/api/v1/tasks/{tid}/review/confirm',json={'expected_revision':initial['revision'],'confirm_all':True}).status_code==404


def test_questions_answers_survive_restart_and_memory_truncation(db):
    tid=store.create('写PRD','')['id'];store.update(tid,'running','处理中')
    question=agent.QuestionArgs(questions=[{'question':'仅查看还是编辑？','recommendation':'仅查看','reason':'影响权限范围'}])
    assert store.wait_for_input(tid,question.render(),0)
    child=store.create_followup(tid,'按推荐')
    store.init()
    history=store.task_history(child['id'])
    memory=json.loads(agent.clarification_memory(history))
    assert memory['records'][0]['answer']=='按推荐'
    assert '仅查看' in memory['records'][0]['question']
    huge=json.loads(agent.clarification_memory([{'question':'问'*7000},{'goal':'答'}]))
    assert huge['omitted']==1
    assert store.get(tid)['status']=='waiting'


def test_structured_questions_and_review_items_are_bounded():
    q={'question':'问题','recommendation':'建议','reason':'影响'}
    assert agent.QuestionArgs(question='旧格式').render()=='旧格式'
    with pytest.raises(ValueError): agent.QuestionArgs(questions=[q]*4)
    with pytest.raises(ValueError): agent.QuestionArgs(question='旧',questions=[q])
    with pytest.raises(ValueError): agent.SaveArgs(content='稿',review_items=[' '])
    with pytest.raises(ValueError): agent.SaveArgs(content='稿',review_items=['建议']*9)
    assert 'question' not in agent.QUESTION_SCHEMA['properties']


def test_review_save_atomic_and_office_restore(db):
    tid=store.create('任务','')['id'];store.update(tid,'running','处理中');store.add_correction(tid,'新要求')
    assert not store.finish(tid,'旧稿',0,['旧建议'])
    assert review.get(tid)['items']==[]
    with pytest.raises(ValueError): store.finish(tid,'稿',1,[' '])
    assert store.get(tid)['status']=='running'
    doc=OfficeDocument.model_validate({'kind':'xlsx','title':'清单','sheets':[{'name':'需求','rows':[['事项'],['待确认']]}]})
    assert library.finish_office(tid,doc,1,['确认范围'])
    initial=review.get(tid);review.confirm(tid,initial['revision'])
    restored=store.restore(tid,tid)
    assert review.get(restored['id'])['status']=='pending'
    assert review.get(tid)['status']=='confirmed'


def test_section_plan_review_persists(db):
    tid=store.create('长稿','')['id'];store.update(tid,'running','处理中')
    assert store.draft_write(tid,'plan',0,titles=['一','二'],review_items=['范围待确认']) is None
    assert store.draft_write(tid,'section',0,position=1,content='一') is None
    assert store.draft_write(tid,'section',0,position=2,content='二') is None
    assert store.draft_write(tid,'finish',0) is None
    assert review.get(tid)['items']==['范围待确认']
    assert review.get(tid)['status']=='pending'


def test_partial_answer_guard_and_explicit_deferral(db):
    tid=store.create('PRD','')['id'];store.update(tid,'running','处理中')
    qs=[{'question':'哪个部门','recommendation':'产品部','reason':'范围'},{'question':'是否只读','recommendation':'只读','reason':'权限'}]
    store.wait_for_input(tid,'两题',0,qs)
    child=store.create_followup(tid,'首批产品部')
    with pytest.raises(ValueError): review.require_answers(child['id'],[{'question_index':1,'answer_quote':'产品部'}])
    with pytest.raises(ValueError): review.require_answers(child['id'],[{'question_index':1,'answer_quote':'产品部'},{'question_index':2,'answer_quote':'产品部'}])
    with pytest.raises(ValueError): review.require_answers(child['id'],[{'question_index':1,'answer_quote':'产品部'},{'question_index':2,'answer_quote':'只读'}])
    accepted=store.create_followup(tid,'按推荐')
    review.require_answers(accepted['id'],None)
    deferred=store.create_followup(tid,'我还不确定，先出草稿，标明假设。')
    review.require_answers(deferred['id'],None,'先出草稿')
    refused=store.create_followup(tid,'不要先出草稿')
    with pytest.raises(ValueError): review.require_answers(refused['id'],None,'先出草稿')
    full=store.create_followup(tid,'首批产品部，只读')
    review.require_answers(full['id'],[{'question_index':1,'answer_quote':'产品部'},{'question_index':2,'answer_quote':'只读'}])


def test_agent_partial_reply_cannot_save_before_remaining_question(db, monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','test-key');monkeypatch.setenv('MODEL_BASE_URL','https://example.test');monkeypatch.setenv('MODEL_NAME','test-model')
    tid=store.create('PRD','')['id'];store.update(tid,'running','处理中')
    qs=[{'question':'部门？','recommendation':'产品部','reason':'范围'},{'question':'权限？','recommendation':'只读','reason':'权限'}]
    store.wait_for_input(tid,'部门与权限两题',0,qs)
    child=store.create_followup(tid,'产品部')['id']
    steps=[('read_previous_result','{}'),('save_artifact',json.dumps({'content':'不能提前保存的稿','answered_questions':[{'question_index':1,'answer_quote':'产品部'}]})),('ask_user',json.dumps({'questions':[qs[1]]}))]
    seen=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs):
            seen.append(json.loads(json.dumps(kwargs['json']['messages'])))
            name,args=steps[len(seen)-1]
            class Response:
                def raise_for_status(self): pass
                def json(self): return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(len(seen)),'type':'function','function':{'name':name,'arguments':args}}]}}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}
            return Response()
    monkeypatch.setattr(agent.httpx,'Client',Client)
    agent.run(child)
    assert store.get(child)['status']=='waiting'
    assert '权限' in store.get(child)['result']
    assert '尚未逐项取得用户答复' in seen[-1][-1]['content']
    assert '不能提前保存的稿' not in store.get(child)['result']


def test_malformed_tool_json_gets_bounded_repair(db, monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY','test-key');monkeypatch.setenv('MODEL_BASE_URL','https://example.test');monkeypatch.setenv('MODEL_NAME','test-model')
    task=store.create('测试JSON修复','')
    seen=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            seen.append(json.loads(json.dumps(kwargs['json']['messages'])))
            args='{broken' if len(seen)==1 else json.dumps({'content':'正确稿','review_items':['建议一']})
            class Response:
                def raise_for_status(self):pass
                def json(self):return {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':str(len(seen)),'type':'function','function':{'name':'save_artifact','arguments':args}}]}}],'usage':{'prompt_tokens':10,'completion_tokens':10}}
            return Response()
    monkeypatch.setattr(agent.httpx,'Client',Client);agent.run(task['id'])
    assert store.get(task['id'])['status']=='completed'
    assert review.get(task['id'])['items']==['建议一']
    assert '不是有效JSON' in seen[1][-1]['content']
    assert seen[1][-2]['tool_calls'][0]['function']['arguments']=='{}'
