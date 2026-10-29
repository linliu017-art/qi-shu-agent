from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from fastapi.testclient import TestClient
from app.main import app
from app import store


def completed(goal='原目标', result='第一行\n保留内容'):
    task = store.create(goal, '虚构资料')
    store.update(task['id'], 'running', '处理中')
    assert store.finish(task['id'], result, 0)
    return task['id']


def test_version_tree_restore_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'versions.sqlite'))
    with TestClient(app) as client:
        root = completed()
        child = store.create_followup(root,'改第一行')['id']
        store.update(child,'running','处理中')
        store.finish(child,'第二行\n保留内容',0)
        branch = store.create_followup(root,'分支')['id']
        store.update(branch,'running','处理中')
        store.finish(branch,'分支\n保留内容',0)
        versions = client.get(f'/api/v1/tasks/{child}/versions').json()['versions']
        assert {v['id'] for v in versions} == {root,child,branch}
        diff = client.get(f'/api/v1/tasks/{child}/diff',params={'base_id':root}).json()
        assert diff['changes'] == [{'kind':'delete','lines':['第一行']},{'kind':'insert','lines':['第二行']},{'kind':'equal','lines':['保留内容']}]
        restored = client.post(f'/api/v1/tasks/{child}/restore',json={'source_id':root})
        assert restored.status_code == 201
        tid = restored.json()['id']
        assert store.get(tid)['result'] == store.get(root)['result']
        assert store.get(child)['result'] == '第二行\n保留内容'
        assert store.task_usage(tid) == {'input_tokens':0,'output_tokens':0}
        store.init()
        assert len(store.versions(tid)) == 4
        assert store.context_link(tid)['parent_id'] == child
        third = store.create_followup(tid,'继续修改')['id']
        assert store.original_goal(third) == '原目标'
        assert len(store.task_history(third)) == 4


def test_reject_unrelated_and_incomplete(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'versions.sqlite'))
    with TestClient(app) as client:
        root, other = completed(), completed('另一成果')
        pending = store.create_followup(root,'未完成')['id']
        for source in [other,pending,'missing']:
            assert client.post(f'/api/v1/tasks/{root}/restore',json={'source_id':source}).status_code == 409
            assert client.get(f'/api/v1/tasks/{root}/diff',params={'base_id':source}).status_code == 409
        assert client.get(f'/api/v1/tasks/{pending}/export.docx').status_code == 409
        assert client.get('/api/v1/tasks/missing/export.docx').status_code == 404
        with store.connection() as db:
            db.execute("UPDATE tasks SET owner_id='other' WHERE id=?", (other,))
        assert client.get(f'/api/v1/tasks/{other}/versions').status_code == 404


def test_word_export_structure(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'versions.sqlite'))
    with TestClient(app) as client:
        tid = completed(result='# 客户需求\n\n**明确事实**与待确认项\n\n- 项目状态\n- 负责人\n\n| 需求 | 依据 |\n| --- | --- |\n| 预算 | 未确定 |\n\n```\n安全代码示例\n```\n<script>不可执行</script>')
        r = client.get(f'/api/v1/tasks/{tid}/export.docx')
        assert r.status_code == 200
        assert r.headers['cache-control'] == 'no-store'
        with ZipFile(BytesIO(r.content)) as archive:
            xml = ET.fromstring(archive.read('word/document.xml'))
            ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            assert len(xml.findall('.//w:tbl',ns)) == 1
            assert len(xml.findall('.//w:tr',ns)) == 2
            text = ''.join(xml.itertext())
            assert '预算' in text and '未确定' in text and '明确事实' in text
            assert not any('vba' in name.lower() for name in archive.namelist())
