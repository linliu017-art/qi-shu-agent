import jwt
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import office_api,store
from test_native_office import make_result,office_file


SECRET='virtual-editor-test-secret-1234567890'


@pytest.fixture
def configured_client(tmp_path,monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH',str(tmp_path/'editor.sqlite'))
    monkeypatch.setenv('OFFICE_EDITOR_ENABLED','1')
    monkeypatch.setenv('OFFICE_EDITOR_SECRET',SECRET)
    monkeypatch.setenv('OFFICE_EDITOR_ORIGIN','http://127.0.0.1:18080')
    monkeypatch.setenv('OFFICE_STORAGE_ORIGIN','http://127.0.0.1:28081')
    with TestClient(app) as client:yield client


def auth(payload,secret=SECRET):return {'Authorization':'Bearer '+jwt.encode({'payload':payload},secret,algorithm='HS256')}


def start(client,kind='pptx'):
    tid=make_result(kind);response=client.post('/api/v1/office-editor/sessions',json={'task_id':tid});assert response.status_code==201
    return tid,response.json()


def test_editor_disabled_by_default_and_rejects_remote_origins(configured_client,monkeypatch):
    tid=make_result('pptx');monkeypatch.delenv('OFFICE_EDITOR_ENABLED')
    assert configured_client.post('/api/v1/office-editor/sessions',json={'task_id':tid}).status_code==503
    monkeypatch.setenv('OFFICE_EDITOR_ENABLED','1');monkeypatch.setenv('OFFICE_EDITOR_ORIGIN','https://example.com')
    assert configured_client.post('/api/v1/office-editor/sessions',json={'task_id':tid}).status_code==503


def test_editor_configuration_and_signed_snapshot(configured_client):
    tid,data=start(configured_client);sid=data['session_id'];cfg=data['config']
    assert cfg['document']['key']==sid and cfg['document']['fileType']=='pptx'
    assert jwt.decode(cfg['token'],SECRET,algorithms=['HS256'])['document']['url']==cfg['document']['url']
    endpoint=f'/api/v1/office-editor/sessions/{sid}/file';url=cfg['document']['url']
    assert configured_client.get(endpoint).status_code==403
    assert configured_client.get(endpoint,headers=auth({'url':'http://example.com'})).status_code==403
    result=configured_client.get(endpoint,headers=auth({'url':url}));assert result.status_code==200 and result.content.startswith(b'PK')
    assert len(store.versions(tid))==1


def test_presentation_preview_uses_signed_read_only_session(configured_client):
    tid=make_result('pptx')
    response=configured_client.post('/api/v1/office-editor/sessions',json={'task_id':tid,'mode':'view'})
    assert response.status_code==201
    config=response.json()['config']
    assert config['editorConfig']['mode']=='view' and config['document']['permissions']['edit'] is False
    assert jwt.decode(config['token'],SECRET,algorithms=['HS256'])['editorConfig']['mode']=='view'


@pytest.mark.parametrize('kind',['docx','xlsx','pptx'])
def test_import_original_preserves_bytes_and_binds_source(configured_client,kind):
    from app import library
    raw=office_file(kind)
    result=configured_client.post('/api/v1/office-editor/import',files={'file':('original.'+kind,raw)})
    assert result.status_code==201
    tid=result.json()['id']
    assert configured_client.get(f'/api/v1/tasks/{tid}/export/{kind}').content==raw
    sources=library.sources(tid)
    assert len(sources)==1 and library.get(sources[0]['id'])['content']==raw


def test_import_original_rejects_invalid_file_without_writing(configured_client):
    before=len(store.list_tasks())
    response=configured_client.post('/api/v1/office-editor/import',files={'file':('broken.pptx',b'bad')})
    assert response.status_code==400 and len(store.list_tasks())==before


def test_callback_signed_save_idempotence_and_tampering(configured_client,monkeypatch):
    tid,data=start(configured_client);sid=data['session_id'];raw=office_file('pptx')
    url='http://127.0.0.1:18080/cache/files/example.pptx';body={'key':sid,'status':2,'url':url};endpoint=f'/api/v1/office-editor/sessions/{sid}/callback'
    monkeypatch.setattr(office_api,'_download',lambda supplied,origin:raw)
    assert configured_client.post(endpoint,json=body).json()=={'error':1}
    assert configured_client.post(endpoint,json=body,headers=auth({**body,'status':1})).json()=={'error':1}
    assert configured_client.post(endpoint,json=body,headers=auth(body)).json()=={'error':0}
    status=configured_client.get(f'/api/v1/office-editor/sessions/{sid}').json();assert status['status']=='saved'
    assert configured_client.post(endpoint,json=body,headers=auth(body)).json()=={'error':0}
    assert len(store.versions(tid))==2
    assert configured_client.get(f'/api/v1/office-editor/sessions/{sid}/file',headers=auth({'url':data['config']['document']['url']})).status_code==404


def test_callback_retains_unparseable_edit_for_recovery(configured_client,monkeypatch):
    tid,data=start(configured_client,'xlsx');sid=data['session_id'];raw=b'broken editor output'
    monkeypatch.setattr(office_api,'_download',lambda supplied,origin:raw)
    body={'key':sid,'status':2,'url':'http://127.0.0.1:18080/cache/files/result.xlsx'}
    assert configured_client.post(f'/api/v1/office-editor/sessions/{sid}/callback',json=body,headers=auth(body)).json()=={'error':0}
    state=configured_client.get(f'/api/v1/office-editor/sessions/{sid}').json()
    assert state['status']=='failed' and state['can_recover']
    assert configured_client.get(f'/api/v1/office-editor/sessions/{sid}/recovery').content==raw
    assert len(store.versions(tid))==1


def test_concurrent_editor_conflict_retains_recovery_file(configured_client,monkeypatch):
    tid,data=start(configured_client,'docx');second=configured_client.post('/api/v1/office-editor/sessions',json={'task_id':tid}).json();raw=office_file('docx')
    monkeypatch.setattr(office_api,'_download',lambda supplied,origin:raw)
    for info,wanted in [(data,0),(second,1)]:
        sid=info['session_id'];body={'key':sid,'status':2,'url':'http://127.0.0.1:18080/cache/files/result.docx'}
        assert configured_client.post(f'/api/v1/office-editor/sessions/{sid}/callback',json=body,headers=auth(body)).json()=={'error':wanted}
    sid=second['session_id'];status=configured_client.get(f'/api/v1/office-editor/sessions/{sid}').json()
    assert status['status']=='conflict' and status['can_recover']
    assert configured_client.get(f'/api/v1/office-editor/sessions/{sid}/recovery').content==raw
    assert len(store.versions(tid))==2


@pytest.mark.parametrize('kind',['docx','xlsx','pptx'])
def test_native_version_download_and_unsafe_paths_are_guarded(configured_client,monkeypatch,kind):
    tid,data=start(configured_client,kind);sid=data['session_id'];raw=office_file(kind)
    monkeypatch.setattr(office_api,'_download',lambda supplied,origin:raw)
    body={'key':sid,'status':2,'url':f'http://127.0.0.1:18080/cache/files/result.{kind}'}
    assert configured_client.post(f'/api/v1/office-editor/sessions/{sid}/callback',json=body,headers=auth(body)).json()=={'error':0}
    new_id=configured_client.get(f'/api/v1/office-editor/sessions/{sid}').json()['task_id']
    info=configured_client.get(f'/api/v1/tasks/{new_id}').json()
    assert info['native_office'] and info['artifact_kind']==kind
    assert configured_client.get(f'/api/v1/tasks/{new_id}/export/{kind}').content==raw
    assert configured_client.post(f'/api/v1/tasks/{new_id}/corrections',json={'content':'修改'}).status_code==409
    assert configured_client.post(f'/api/v1/tasks/{new_id}/edit',json={'expected_version_id':new_id,'content':'损坏'}).status_code==409
    assert configured_client.get(f'/api/v1/tasks/{new_id}/diff',params={'base_id':tid}).status_code==409
    cards=configured_client.get('/api/v1/artifacts').json()['artifacts'];new_card=next(x for x in cards if x['task_id']==new_id)
    assert new_card['native_office'] and new_card['kind']==kind
    restored=configured_client.post(f'/api/v1/tasks/{new_id}/restore',json={'source_id':new_id}).json()['id']
    assert configured_client.get(f'/api/v1/tasks/{restored}/export/{kind}').content==raw


def test_callback_holds_complex_loss_for_explicit_review(configured_client,monkeypatch):
    from io import BytesIO
    from docx import Document
    from app import library
    root=make_result('docx');original=office_file('docx');native=library.save_native_version(root,root,'original.docx',original)
    data=configured_client.post('/api/v1/office-editor/sessions',json={'task_id':native['id']}).json();sid=data['session_id']
    changed=Document();changed.add_paragraph('edited');out=BytesIO();changed.save(out);candidate=out.getvalue()
    monkeypatch.setattr(office_api,'_download',lambda supplied,origin:candidate)
    body={'key':sid,'status':2,'url':'http://127.0.0.1:18080/cache/files/result.docx'}
    assert configured_client.post(f'/api/v1/office-editor/sessions/{sid}/callback',json=body,headers=auth(body)).json()=={'error':0}
    state=configured_client.get(f'/api/v1/office-editor/sessions/{sid}').json();assert state['status']=='review_required' and state['warnings']
    assert configured_client.get(f'/api/v1/office-editor/sessions/{sid}/recovery').content==candidate
    approved=configured_client.post(f'/api/v1/office-editor/sessions/{sid}/approve').json();assert approved['status']=='saved'
    assert configured_client.get(f'/api/v1/tasks/{approved["task_id"]}/export/docx').content==candidate
    assert library.native_office(native['id'])['content']==original
