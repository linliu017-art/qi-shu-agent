from concurrent.futures import ThreadPoolExecutor
import pytest
from app import office_sessions,library,store
from test_native_office import make_result,office_file


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setenv('AGENT_DB_PATH',str(tmp_path/'sessions.sqlite'))
    store.init()


@pytest.mark.parametrize('kind',['docx','xlsx','pptx'])
def test_session_save_is_atomic_idempotent_and_restorable(db,kind):
    parent=make_result(kind);session=office_sessions.create(parent);sid=session['id'];raw=office_file(kind)
    assert session['status']=='open' and len(store.versions(parent))==1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:office_sessions.finish(sid,raw),range(2)))
    assert results[0]==results[1] and results[0]['status']=='saved'
    new_id=results[0]['task_id'];assert library.native_office(new_id)['content']==raw
    assert len(store.versions(parent))==2
    store.init();assert office_sessions.get(sid)['result_id']==new_id
    restored=store.restore(new_id,new_id);assert library.native_office(restored['id'])['content']==raw
    with pytest.raises(ValueError):office_sessions.finish(sid,session['snapshot'])


def test_concurrent_session_conflict_preserves_returned_file(db):
    parent=make_result('docx');first=office_sessions.create(parent);second=office_sessions.create(parent)
    first_raw=office_file('docx');assert office_sessions.finish(first['id'],first_raw)['status']=='saved'
    second_raw=office_file('docx');conflict=office_sessions.finish(second['id'],second_raw)
    assert conflict['status']=='conflict' and conflict['task_id'] is None
    store.init();recovered=office_sessions.get(second['id']);assert recovered['recovery']==second_raw
    assert office_sessions.finish(second['id'],second_raw)==conflict
    assert len(store.versions(parent))==2


def test_unchanged_session_creates_no_new_version(db):
    parent=make_result('xlsx');session=office_sessions.create(parent)
    result=office_sessions.finish(session['id'],session['snapshot'])
    assert result=={'status':'unchanged','task_id':parent} and len(store.versions(parent))==1
    assert office_sessions.finish(session['id'],session['snapshot'])==result


def test_session_owner_and_invalid_file_are_rejected(db):
    parent=make_result('docx');session=office_sessions.create(parent)
    with pytest.raises(ValueError):office_sessions.finish(session['id'],b'invalid')
    assert office_sessions.get(session['id'])['status']=='open'
    with store.connection() as conn:conn.execute("UPDATE tasks SET owner_id='other' WHERE id=?",(parent,))
    assert office_sessions.get(session['id']) is None
    with pytest.raises(ValueError):office_sessions.finish(session['id'],office_file('docx'))


def test_complex_loss_is_held_until_explicit_review(db):
    from io import BytesIO
    from docx import Document
    root=make_result('docx');original=office_file('docx');native=library.save_native_version(root,root,'原稿.docx',original)
    session=office_sessions.create(native['id'])
    changed=Document();changed.add_paragraph('编辑后的文字');out=BytesIO();changed.save(out);candidate=out.getvalue()
    result=office_sessions.finish(session['id'],candidate)
    assert result['status']=='review_required' and len(store.versions(root))==2
    pending=office_sessions.get(session['id']);assert pending['recovery']==candidate and '图片或媒体' in pending['review_details']
    assert library.native_office(native['id'])['content']==original
    store.init();assert office_sessions.get(session['id'])['recovery']==candidate
    approved=office_sessions.approve(session['id']);assert approved['status']=='saved'
    assert library.native_office(approved['task_id'])['content']==candidate
    assert office_sessions.approve(session['id'])==approved
    assert library.native_office(native['id'])['content']==original
