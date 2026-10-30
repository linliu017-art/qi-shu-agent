from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app import store
from app.main import app, pool


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH', str(tmp_path/'requests.sqlite'))
    scheduled = []
    monkeypatch.setattr(pool, 'submit', lambda fn, tid: scheduled.append(tid))
    with TestClient(app) as client:
        yield client, scheduled


def test_concurrent_retries_schedule_only_once(client):
    api, scheduled = client
    data = {'goal': '虚构整理', 'client_request_id': 'retry-1'}
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: api.post('/api/v1/tasks', json=data), range(8)))
    assert all(r.status_code == 201 for r in results)
    ids = {r.json()['id'] for r in results}
    assert len(ids) == 1 and scheduled == list(ids)
    store.init()
    retry = api.post('/api/v1/tasks', json=data).json()
    assert retry['id'] in ids and retry['status'] == 'interrupted'
    assert len(scheduled) == 1


def test_conflict_and_old_clients(client):
    api, scheduled = client
    first = api.post('/api/v1/tasks', json={'goal': 'A', 'client_request_id': 'one'})
    conflict = api.post('/api/v1/tasks', json={'goal': 'B', 'client_request_id': 'one'})
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'CONFLICT'
    assert store.get(first.json()['id'])['goal'] == 'A'
    assert len(scheduled) == 1
    ids = [api.post('/api/v1/tasks', json={'goal': 'old client'}).json()['id'] for _ in range(2)]
    assert ids[0] != ids[1]


def test_invalid_source_rolls_back_key(client):
    api, scheduled = client
    bad = api.post('/api/v1/tasks', json={'goal': 'A', 'source_ids': ['missing'], 'client_request_id': 'rollback'})
    assert bad.status_code == 400 and not scheduled and not store.list_tasks()
    assert api.post('/api/v1/tasks', json={'goal': 'A', 'client_request_id': 'rollback'}).status_code == 201
    assert len(scheduled) == 1


def test_schedule_failure_is_retrievable_without_resubmission(client, monkeypatch):
    api, _ = client
    def fail(*args):
        raise RuntimeError('executor unavailable')
    monkeypatch.setattr(pool, 'submit', fail)
    data = {'goal': 'A', 'client_request_id': 'queue-failure'}
    first = api.post('/api/v1/tasks', json=data).json()
    retry = api.post('/api/v1/tasks', json=data).json()
    assert first['id'] == retry['id'] and retry['status'] == 'failed'


@pytest.mark.parametrize('key', ['', 'bad key', 'x'*65])
def test_invalid_request_key(client, key):
    api, scheduled = client
    assert api.post('/api/v1/tasks', json={'goal':'A','client_request_id':key}).status_code == 422
    assert not scheduled
