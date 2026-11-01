"""Durable native Office editing sessions; integration endpoints are not enabled."""
import json
from datetime import datetime,timezone
from hashlib import sha256
from uuid import uuid4
from . import store,library
from .office_integrity import potential_losses


def create(tid):
    base=library.prepare_native_editor_file(tid)
    sid=uuid4().hex
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        family=store.versions(tid)
        if not family or family[-1]['id']!=tid or db.execute('SELECT 1 FROM task_context WHERE parent_id=?',(tid,)).fetchone():
            raise ValueError('版本已变化，请刷新最新版本后编辑')
        db.execute('INSERT INTO native_office_sessions (id,owner_id,base_id,kind,snapshot,snapshot_hash,status,result_id,result_hash,recovery,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (sid,'local-user',tid,base['kind'],base['content'],base['sha256'],'open',None,None,None,datetime.now(timezone.utc).isoformat()))
    return get(sid)


def get(sid):
    with store.connection() as db:
        row=db.execute("SELECT s.* FROM native_office_sessions s JOIN tasks t ON t.id=s.base_id WHERE s.id=? AND s.owner_id='local-user' AND t.owner_id='local-user'",(sid,)).fetchone()
        return dict(row) if row else None


def finish(sid,raw):
    """Persist a valid result exactly once; retain bytes on a version conflict."""
    session=get(sid)
    if not session:raise ValueError('编辑会话不存在')
    _,kind,text=library.inspect_file('result.'+session['kind'],raw,allow_empty=True)
    if kind!=session['kind']:raise ValueError('不能通过编辑更换成果格式')
    digest=sha256(raw).hexdigest()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM native_office_sessions WHERE id=? AND owner_id='local-user'",(sid,)).fetchone()
        if not row:raise ValueError('编辑会话不存在')
        if row['status'] in ('saved','unchanged','conflict','review_required'):
            if row['result_hash']==digest:return {'status':row['status'],'task_id':row['result_id']}
            raise ValueError('编辑会话已结束，不能写入不同结果')
        if row['status']!='open':raise ValueError('编辑会话不可保存')
        if digest==row['snapshot_hash']:
            db.execute("UPDATE native_office_sessions SET status='unchanged',result_id=base_id,result_hash=? WHERE id=?",(digest,sid))
            return {'status':'unchanged','task_id':row['base_id']}
        warnings=potential_losses(row['snapshot'],raw,kind)
        if warnings:
            db.execute("UPDATE native_office_sessions SET status='review_required',result_hash=?,recovery=?,review_details=? WHERE id=?",(digest,raw,json.dumps(warnings,ensure_ascii=False),sid))
            return {'status':'review_required','task_id':None}
        try:
            new_id=library._save_native_tx(db,row['base_id'],row['base_id'],kind,raw,text)
        except ValueError:
            # A concurrent version does not discard the editor's valid result.
            db.execute("UPDATE native_office_sessions SET status='conflict',result_hash=?,recovery=? WHERE id=?",(digest,raw,sid))
            return {'status':'conflict','task_id':None}
        db.execute("UPDATE native_office_sessions SET status='saved',result_id=?,result_hash=? WHERE id=?",(new_id,digest,sid))
        return {'status':'saved','task_id':new_id}


def retain_failed(sid,raw):
    """Keep a downloaded candidate when it cannot safely be made a version."""
    digest=sha256(raw).hexdigest()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT status,result_hash FROM native_office_sessions WHERE id=? AND owner_id='local-user'",(sid,)).fetchone()
        if not row:return False
        if row['status']=='failed':return row['result_hash']==digest
        if row['status']!='open':return False
        db.execute("UPDATE native_office_sessions SET status='failed',result_hash=?,recovery=? WHERE id=?",(digest,raw,sid))
        return True


def approve(sid):
    """Explicitly save the already-reviewed candidate; preserve it on conflict."""
    session=get(sid)
    if not session:raise ValueError('编辑会话不存在')
    if session['status']=='saved':return {'status':'saved','task_id':session['result_id']}
    if session['status']!='review_required' or session['recovery'] is None:raise ValueError('没有待确认的编辑结果')
    raw=session['recovery'];_,kind,text=library.inspect_file('result.'+session['kind'],raw,allow_empty=True)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM native_office_sessions WHERE id=? AND owner_id='local-user'",(sid,)).fetchone()
        if not row:raise ValueError('编辑会话不存在')
        if row['status']=='saved':return {'status':'saved','task_id':row['result_id']}
        if row['status']!='review_required' or row['recovery']!=raw:raise ValueError('编辑会话状态已变化')
        try:new_id=library._save_native_tx(db,row['base_id'],row['base_id'],kind,raw,text)
        except ValueError:
            db.execute("UPDATE native_office_sessions SET status='conflict' WHERE id=?",(sid,))
            return {'status':'conflict','task_id':None}
        db.execute("UPDATE native_office_sessions SET status='saved',result_id=? WHERE id=?",(new_id,sid))
        return {'status':'saved','task_id':new_id}
