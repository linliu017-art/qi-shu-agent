"""Human confirmation is separate from successful model execution."""
import hashlib
import json
from datetime import datetime, timezone
from . import store


def write_items(db, tid, items):
    if items is None:
        return
    if not isinstance(items, list) or len(items) > 8 or any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in items):
        raise ValueError('待确认项须为最多8条非空文字，每条不超过500字')
    db.execute('INSERT INTO task_reviews(task_id,items,confirmed_at) VALUES (?,?,NULL) ON CONFLICT(task_id) DO UPDATE SET items=excluded.items,confirmed_at=NULL',
               (tid, json.dumps(items, ensure_ascii=False)))


def inherit(db, parent_id, tid):
    row = db.execute("SELECT r.items,r.confirmed_at FROM task_reviews r JOIN tasks t ON t.id=r.task_id WHERE t.id=? AND t.owner_id='local-user'", (parent_id,)).fetchone()
    if row:
        write_items(db, tid, [] if row['confirmed_at'] else json.loads(row['items']))


def _read(db, task):
    row = db.execute('SELECT items,confirmed_at FROM task_reviews WHERE task_id=?', (task['id'],)).fetchone()
    items = json.loads(row['items']) if row else []
    confirmed = row['confirmed_at'] if row else None
    revision = hashlib.sha256(json.dumps([task['result'], items], ensure_ascii=False).encode()).hexdigest()
    has_child = db.execute('SELECT 1 FROM task_context WHERE parent_id=? LIMIT 1', (task['id'],)).fetchone()
    return {'status': 'confirmed' if confirmed else 'pending', 'items': items, 'confirmed_at': confirmed,
            'revision': revision, 'can_confirm': task['status']=='completed' and not has_child and not confirmed}


def get(tid):
    with store.connection() as db:
        task = db.execute("SELECT id,result,status FROM tasks WHERE id=? AND owner_id='local-user'", (tid,)).fetchone()
        if not task:
            raise LookupError('任务不存在')
        return _read(db, task)


def confirm(tid, expected_revision):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        task = db.execute("SELECT id,result,status FROM tasks WHERE id=? AND owner_id='local-user'", (tid,)).fetchone()
        if not task:
            raise LookupError('任务不存在')
        current = _read(db, task)
        if task['status'] != 'completed' or current['revision'] != expected_revision or db.execute('SELECT 1 FROM task_context WHERE parent_id=? LIMIT 1', (tid,)).fetchone():
            raise ValueError('草稿版本或状态已变化，请打开最新成果后确认')
        if not current['confirmed_at']:
            db.execute('INSERT INTO task_reviews(task_id,items,confirmed_at) VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET confirmed_at=excluded.confirmed_at',
                       (tid, json.dumps(current['items'], ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        return _read(db, task)


def require_answers(tid, answers, defer_quote=None):
    """A structured open question needs evidence in the user's reply before saving.

    Quotes establish provenance, not semantic correctness; that remains model/eval work.
    """
    link = store.context_link(tid)
    if not link or link['parent_status'] != 'waiting':
        return
    with store.connection() as db:
        row = db.execute('SELECT questions FROM task_clarifications WHERE task_id=?', (link['parent_id'],)).fetchone()
    if not row:  # Legacy question strings remain compatible.
        return
    questions = json.loads(row['questions'])
    task = store.get(tid)
    reply = task['goal']
    if defer_quote and defer_quote in reply and any(phrase in defer_quote for phrase in ('先出草稿', '先写草稿', '先草拟', '先按假设', '按假设先写')) and not any(word in reply for word in ('不要', '不允许', '禁止', '不能', '别先')):
        return
    # An explicit whole-response acceptance resolves all recommendations; no substring/negation inference.
    if reply.strip().strip('。！!') in ('按推荐', '全部按推荐', '都按推荐', '按你的推荐', '全部按你的推荐'):
        return
    evidence = answers or []
    required = set(range(1, len(questions)+1))
    indices = [item['question_index'] for item in evidence]
    quotes = [item['answer_quote'] for item in evidence]
    supplied = reply + '\n' + '\n'.join(c['content'] for c in store.corrections_since(tid, 0))
    if set(indices) != required or len(indices) != len(required) or len(set(quotes)) != len(quotes) or any(q not in supplied for q in quotes):
        raise ValueError('上轮关键问题尚未逐项取得用户答复。保存需answered_questions列出每个question_index及本轮用户回答中的不同原文answer_quote；没有答复的项必须继续ask_user，不能擅自改成草稿假设。')
