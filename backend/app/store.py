import os
import json
import sqlite3
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4


def connection():
    path = Path(os.environ.get("AGENT_DB_PATH", Path(__file__).resolve().parents[2] / "data" / "agent.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init():
    from . import library
    with connection() as db:
        library.init(db)
        db.execute("CREATE TABLE IF NOT EXISTS task_clarifications (task_id TEXT PRIMARY KEY, questions TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS task_reviews (task_id TEXT PRIMARY KEY, items TEXT NOT NULL, confirmed_at TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, goal TEXT NOT NULL, material TEXT NOT NULL, status TEXT NOT NULL, progress TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS task_requests (owner_id TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(owner_id, request_id))")
        db.execute("CREATE TABLE IF NOT EXISTS task_context (task_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, parent_status TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS usage_records (task_id TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS usage_cache_records (usage_id INTEGER PRIMARY KEY, hit_tokens INTEGER NOT NULL, miss_tokens INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS draft_plans (task_id TEXT PRIMARY KEY, titles TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS draft_sections (task_id TEXT NOT NULL, position INTEGER NOT NULL, content TEXT NOT NULL, PRIMARY KEY(task_id, position))")
        db.execute("CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, content TEXT NOT NULL)")
        db.execute("UPDATE tasks SET status='interrupted', progress='服务重启，任务已中断；保存的资料仍可查看' WHERE status IN ('running','queued')")


def create(goal, material, source_ids=None):
    return create_once(goal, material, source_ids)[0]


class RequestConflict(ValueError):
    pass


def create_once(goal, material, source_ids=None, request_id=None):
    """Atomically bind a retry key to a task; only the creator may schedule it."""
    source_ids = source_ids or []
    digest = sha256(json.dumps([goal, material, source_ids], ensure_ascii=False).encode()).hexdigest()
    tid = uuid4().hex
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if request_id:
            row = db.execute("SELECT payload_hash,task_id FROM task_requests WHERE owner_id=? AND request_id=?", ("local-user", request_id)).fetchone()
            if row:
                if row['payload_hash'] != digest:
                    raise RequestConflict('该提交标识已用于另一份任务，请重新发起任务')
                task = db.execute("SELECT * FROM tasks WHERE id=? AND owner_id=?", (row['task_id'], "local-user")).fetchone()
                return dict(task), False
        db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)", (tid, "local-user", goal, material, "queued", "等待执行", "", datetime.now(timezone.utc).isoformat()))
        from . import library
        library.bind(db,tid,source_ids)
        if request_id:
            db.execute("INSERT INTO task_requests VALUES (?,?,?,?)", ("local-user", request_id, digest, tid))
    return get(tid), True


def get(tid):
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=? AND owner_id=?", (tid, "local-user")).fetchone()
        return dict(row) if row else None


def update(tid, status, progress, result=None):
    with connection() as db:
        cursor = db.execute("UPDATE tasks SET status=?, progress=?, result=COALESCE(?,result) WHERE id=? AND owner_id=? AND status NOT IN ('cancelled','interrupted')", (status, progress, result, tid, "local-user"))
        return cursor.rowcount == 1


def cancel(tid):
    with connection() as db:
        return db.execute("UPDATE tasks SET status='cancelled', progress='已停止' WHERE id=? AND owner_id=? AND status IN ('queued','running')", (tid, "local-user")).rowcount == 1


def add_correction(tid, content):
    with connection() as db:
        cursor = db.execute("INSERT INTO corrections(task_id,content) SELECT id,? FROM tasks WHERE id=? AND owner_id=? AND status IN ('queued','running')", (content, tid, 'local-user'))
        return cursor.rowcount == 1


def corrections_since(tid, last_id):
    with connection() as db:
        rows = db.execute("SELECT corrections.id, corrections.content FROM corrections JOIN tasks ON tasks.id=corrections.task_id WHERE corrections.task_id=? AND tasks.owner_id=? AND corrections.id>? ORDER BY corrections.id", (tid, 'local-user', last_id)).fetchall()
        return [dict(row) for row in rows]


def finish(tid, result, last_correction, review_items=None):
    with connection() as db:
        cursor = db.execute("UPDATE tasks SET status='completed', progress='成果已保存', result=? WHERE id=? AND owner_id=? AND status='running' AND NOT EXISTS (SELECT 1 FROM corrections WHERE task_id=? AND id>?)", (result, tid, 'local-user', tid, last_correction))
        if cursor.rowcount == 1:
            from . import review
            review.write_items(db, tid, review_items)
        return cursor.rowcount == 1


def list_tasks():
    with connection() as db:
        rows = db.execute("SELECT id, goal, status, progress, created_at FROM tasks WHERE owner_id=? ORDER BY created_at DESC LIMIT 100", ('local-user',)).fetchall()
        return [dict(row) for row in rows]


def list_task_threads():
    """Group execution records by their original task without changing history."""
    with connection() as db:
        rows = db.execute("SELECT t.id,t.goal,t.status,t.progress,t.created_at,c.parent_id FROM tasks t LEFT JOIN task_context c ON c.task_id=t.id WHERE t.owner_id=?", ('local-user',)).fetchall()
    records = {row['id']: dict(row) for row in rows}
    roots = {}

    def root_id(tid):
        path, seen = [], set()
        current = tid
        while current not in roots and records[current]['parent_id'] in records:
            if current in seen:
                raise ValueError('任务上下文存在循环')
            seen.add(current)
            path.append(current)
            current = records[current]['parent_id']
        root = roots.get(current, current)
        for item in path:
            roots[item] = root
        roots[current] = root
        return root

    latest = {}
    for tid, row in records.items():
        root = root_id(tid)
        previous = latest.get(root)
        if previous is None or (row['created_at'], tid) > (previous['created_at'], previous['id']):
            latest[root] = row
    threads = []
    for root, row in latest.items():
        goal = records[root]['goal']
        if goal.startswith('原任务：') and ('\n已有成果：' in goal or '\n待答问题：' in goal):
            goal = goal[len('原任务：'):].split('\n已有成果：', 1)[0].split('\n待答问题：', 1)[0]
        threads.append({'id': row['id'], 'root_id': root, 'goal': goal, 'status': row['status'], 'progress': row['progress'], 'created_at': row['created_at']})
    return sorted(threads, key=lambda row: (row['created_at'], row['id']), reverse=True)[:100]


def wait_for_input(tid, question, last_correction, questions=None):
    with connection() as db:
        cursor = db.execute("UPDATE tasks SET status='waiting', progress='等待补充信息', result=? WHERE id=? AND owner_id=? AND status='running' AND NOT EXISTS (SELECT 1 FROM corrections WHERE task_id=? AND id>?)", (question, tid, 'local-user', tid, last_correction))
        if cursor.rowcount == 1 and questions is not None:
            db.execute('INSERT OR REPLACE INTO task_clarifications VALUES (?,?)', (tid, json.dumps(questions, ensure_ascii=False)))
        return cursor.rowcount == 1


def record_usage(tid, input_tokens, output_tokens, cache_hit=None, cache_miss=None):
    with connection() as db:
        cursor = db.execute("INSERT INTO usage_records(task_id,input_tokens,output_tokens) SELECT id,?,? FROM tasks WHERE id=? AND owner_id=?", (input_tokens, output_tokens, tid, 'local-user'))
        if cursor.rowcount == 1 and cache_hit is not None and cache_miss is not None:
            db.execute("INSERT INTO usage_cache_records(usage_id,hit_tokens,miss_tokens) VALUES(?,?,?)", (cursor.lastrowid, cache_hit, cache_miss))


def task_cache_usage(tid):
    with connection() as db:
        row = db.execute("SELECT count(u.rowid), count(c.usage_id), coalesce(sum(c.hit_tokens),0), coalesce(sum(c.miss_tokens),0) FROM usage_records u LEFT JOIN usage_cache_records c ON c.usage_id=u.rowid JOIN tasks t ON t.id=u.task_id WHERE u.task_id=? AND t.owner_id=?", (tid, 'local-user')).fetchone()
        return {"calls":row[0], "reported_calls":row[1], "hit_tokens":row[2] if row[1] else None, "miss_tokens":row[3] if row[1] else None}


def task_usage(tid):
    with connection() as db:
        row = db.execute("SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) FROM usage_records WHERE task_id=?", (tid,)).fetchone()
        return {"input_tokens": row[0], "output_tokens": row[1]}


def create_followup(parent_id, instruction):
    tid = uuid4().hex
    with connection() as db:
        parent = db.execute("SELECT material,status FROM tasks WHERE id=? AND owner_id=?", (parent_id, "local-user")).fetchone()
        if not parent or parent["status"] not in ("completed", "waiting"):
            return None
        db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)", (tid, "local-user", instruction, parent["material"], "queued", "等待执行", "", datetime.now(timezone.utc).isoformat()))
        db.execute("INSERT INTO task_context(task_id,parent_id,parent_status) VALUES(?,?,?)", (tid, parent_id, parent["status"]))
        from . import library
        library.inherit(db,parent_id,tid)
    return get(tid)


def context_link(tid):
    with connection() as db:
        row = db.execute("SELECT c.parent_id,c.parent_status FROM task_context c JOIN tasks t ON t.id=c.task_id WHERE c.task_id=? AND t.owner_id=?", (tid, "local-user")).fetchone()
        return dict(row) if row else None


def original_goal(tid):
    # Bound traversal without ever modifying older records.
    seen = set()
    current = tid
    for _ in range(100):
        if current in seen:
            raise ValueError("任务上下文存在循环")
        seen.add(current)
        link = context_link(current)
        if not link:
            task = get(current)
            if not task:
                raise ValueError("原任务不存在")
            goal = task["goal"]
            if goal.startswith("原任务：") and ("\n已有成果：" in goal or "\n待答问题：" in goal):
                goal = goal[len("原任务："):].split("\n已有成果：", 1)[0].split("\n待答问题：", 1)[0]
            return goal
        current = link["parent_id"]
    raise ValueError("任务上下文层数超出限制")


def task_history(tid):
    seen = set()
    chain = []
    current = tid
    for _ in range(100):
        if current in seen:
            raise ValueError("任务上下文存在循环")
        seen.add(current)
        task = get(current)
        if not task:
            raise ValueError("任务不存在")
        link = context_link(current)
        goal = task["goal"]
        if not link and goal.startswith("原任务：") and ("\n已有成果：" in goal or "\n待答问题：" in goal):
            goal = goal[len("原任务："):].split("\n已有成果：", 1)[0].split("\n待答问题：", 1)[0]
        corrections = corrections_since(current, 0)
        entry = {"goal": goal, "corrections": [item["content"] for item in corrections]}
        if task['status'] == 'waiting':
            entry['question'] = task['result']
        from . import review
        reviewed = review.get(current)
        if reviewed['items'] or reviewed['status'] == 'confirmed':
            entry['review'] = {'status': reviewed['status'], 'items': reviewed['items'], 'confirmed_at': reviewed['confirmed_at']}
        chain.append(entry)
        if not link:
            break
        current = link["parent_id"]
    else:
        raise ValueError("任务上下文层数超出限制")
    return list(reversed(chain))


def draft(tid):
    with connection() as db:
        plan = db.execute("SELECT d.titles FROM draft_plans d JOIN tasks t ON t.id=d.task_id WHERE d.task_id=? AND t.owner_id=?", (tid, 'local-user')).fetchone()
        if not plan:
            return None
        titles = json.loads(plan['titles'])
        rows = db.execute("SELECT position,content FROM draft_sections WHERE task_id=? ORDER BY position", (tid,)).fetchall()
        saved = {row['position']: row['content'] for row in rows}
        return [{'position': i+1, 'title': title, 'content': saved.get(i+1)} for i,title in enumerate(titles)]


def draft_write(tid, operation, last_correction, titles=None, position=None, content=None, review_items=None):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        task = db.execute("SELECT status FROM tasks WHERE id=? AND owner_id=?", (tid, 'local-user')).fetchone()
        if not task or task['status'] != 'running':
            return '任务已停止或状态改变'
        if db.execute("SELECT 1 FROM corrections WHERE task_id=? AND id>? LIMIT 1", (tid,last_correction)).fetchone():
            return '用户有新的补充，请先处理'
        plan = db.execute("SELECT titles FROM draft_plans WHERE task_id=?", (tid,)).fetchone()
        if operation == 'plan':
            encoded = json.dumps(titles, ensure_ascii=False)
            if plan and json.loads(plan['titles']) != titles:
                return '已有章节计划，不能覆盖；如需调整请说明并新建任务'
            if not plan:
                db.execute("INSERT INTO draft_plans(task_id,titles) VALUES (?,?)", (tid,encoded))
                from . import review
                review.write_items(db, tid, review_items)
            return None
        if not plan:
            return '请先建立章节计划'
        planned = json.loads(plan['titles'])
        if operation == 'section':
            if position < 1 or position > len(planned):
                return '章节序号不在计划范围内'
            row = db.execute("SELECT content FROM draft_sections WHERE task_id=? AND position=?", (tid,position)).fetchone()
            if row:
                return None if row['content'] == content else '该章节已有内容，不能静默覆盖'
            size = db.execute("SELECT COALESCE(sum(length(content)),0) FROM draft_sections WHERE task_id=?", (tid,)).fetchone()[0]
            if size + len(content) > 90000:
                return '分段成果超过总长度限制'
            db.execute("INSERT INTO draft_sections(task_id,position,content) VALUES (?,?,?)", (tid, position, content))
            count = db.execute("SELECT count(*) FROM draft_sections WHERE task_id=?", (tid,)).fetchone()[0]
            db.execute("UPDATE tasks SET progress=? WHERE id=?", (f'已保存 {count}/{len(planned)} 个章节',tid))
            return None
        if operation == 'finish':
            rows = db.execute("SELECT position,content FROM draft_sections WHERE task_id=? ORDER BY position", (tid,)).fetchall()
            if [r['position'] for r in rows] != list(range(1,len(planned)+1)):
                return '章节尚未全部保存，不能合并'
            final = '\n\n'.join(assemble_section(title, r['content']) for title,r in zip(planned,rows))
            if len(final) > 100000:
                return '合并成果超过长度限制'
            db.execute("UPDATE tasks SET status='completed',progress='成果已保存',result=? WHERE id=? AND status='running'", (final,tid))
            return None
        return '不支持的操作'


def resume(tid):
    with connection() as db:
        cursor=db.execute("UPDATE tasks SET status='queued',progress='等待继续已保存的章节' WHERE id=? AND owner_id=? AND status IN ('interrupted','failed') AND EXISTS (SELECT 1 FROM draft_plans WHERE task_id=?)", (tid,'local-user',tid))
        return cursor.rowcount == 1


def assemble_section(title, content):
    text = content.lstrip()
    first = text.split('\n', 1)[0].strip()
    if first.lstrip('#').strip() == title and first.startswith('#'):
        return text
    return '## ' + title + '\n\n' + content


def versions(tid):
    """Traverse both ancestors and descendants; never infer links from prose."""
    with connection() as db:
        rows = db.execute("SELECT t.id,t.goal,t.status,t.created_at,c.parent_id FROM tasks t LEFT JOIN task_context c ON c.task_id=t.id WHERE t.owner_id=?", ('local-user',)).fetchall()
    records = {r['id']: dict(r) for r in rows}
    if tid not in records:
        return []
    root, seen = tid, set()
    while records[root]['parent_id'] in records:
        if root in seen:
            raise ValueError('任务上下文存在循环')
        seen.add(root)
        root = records[root]['parent_id']
    family = {root}
    while True:
        added = {key for key,r in records.items() if r['parent_id'] in family} - family
        if not added:
            break
        family.update(added)
    return sorted([r for key,r in records.items() if key in family and r['status']=='completed'], key=lambda r: (r['created_at'],r['id']))


def restore(tid, source_id):
    allowed = {r['id'] for r in versions(tid)}
    if tid not in allowed or source_id not in allowed:
        return None
    new_id = uuid4().hex
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        source = db.execute("SELECT * FROM tasks WHERE id=? AND owner_id=? AND status='completed'", (source_id,'local-user')).fetchone()
        current = db.execute("SELECT id FROM tasks WHERE id=? AND owner_id=? AND status='completed'", (tid,'local-user')).fetchone()
        if not source or not current:
            return None
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)', (new_id,'local-user',f'恢复历史版本 {source_id[:8]}，以此版本为准',source['material'],'completed','历史版本已恢复为新版本',source['result'],datetime.now(timezone.utc).isoformat()))
        db.execute('INSERT INTO task_context VALUES (?,?,?)', (new_id,tid,'completed'))
        from . import library
        library.inherit(db,source_id,new_id)
        db.execute('INSERT INTO office_artifacts SELECT ?,document FROM office_artifacts WHERE task_id=?',(new_id,source_id))
        db.execute('INSERT INTO native_office_artifacts SELECT ?,kind,sha256,content FROM native_office_artifacts WHERE task_id=?',(new_id,source_id))
    return get(new_id)
