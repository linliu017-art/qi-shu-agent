from fastapi.testclient import TestClient
from app import store
from app.main import app


def test_followups_are_grouped_under_original_task_and_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path / 'threads.sqlite'))
    store.init()
    root = store.create('根据访谈起草 PRD', '访谈资料')['id']
    store.update(root, 'running', '处理中')
    assert store.wait_for_input(root, '首批部门？', 0)
    first = store.create_followup(root, '首批选产品部')['id']
    store.update(first, 'running', '处理中')
    assert store.wait_for_input(first, '只读还是编辑？', 0)
    latest = store.create_followup(first, '只读')['id']
    store.update(latest, 'running', '处理中')
    assert store.finish(latest, '草稿', 0)
    independent = store.create('另一个独立任务', '')['id']
    store.init()

    with TestClient(app) as client:
        threads = client.get('/api/v1/task-threads').json()['tasks']
        assert len(threads) == 2
        thread = next(t for t in threads if t['root_id'] == root)
        assert (thread['id'], thread['goal'], thread['status']) == (latest, '根据访谈起草 PRD', 'completed')
        assert any(t['id'] == independent for t in threads)
        assert client.get(f'/api/v1/tasks/{latest}').json()['original_goal'] == '根据访谈起草 PRD'
        assert len(client.get('/api/v1/tasks').json()['tasks']) == 4
        assert store.task_history(latest)[1]['goal'] == '首批选产品部'
        assert [v['id'] for v in store.versions(latest)] == [latest]
