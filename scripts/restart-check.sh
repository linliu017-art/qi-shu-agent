#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMPDIR_AGENT="$(mktemp -d)"
PORT=18782
PID=""
cleanup(){ [ -z "$PID" ] || { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }; rm -rf "$TMPDIR_AGENT"; }
trap cleanup EXIT
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then echo '测试端口已占用'; exit 1; fi
start(){ (cd "$ROOT/backend" && exec env AGENT_DB_PATH="$TMPDIR_AGENT/data.sqlite" MODEL_API_KEY="" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$TMPDIR_AGENT/server.log" 2>&1) & PID=$!; for i in {1..50}; do if curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then return 0; fi; sleep .1; done; echo '服务启动失败'; exit 1; }
start
echo '服务已启动'
RESPONSE="$(curl -fsS -X POST "http://127.0.0.1:$PORT/api/v1/tasks" -H 'Content-Type: application/json' --data '{"goal":"restart-check-unique","material":"temporary","client_request_id":"restart-key"}')"
ID="$(printf '%s' "$RESPONSE" | "$ROOT/backend/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo '已写入临时任务'
(cd "$ROOT/backend" && AGENT_DB_PATH="$TMPDIR_AGENT/data.sqlite" .venv/bin/python - "$ID" <<'PYCODE'
import sys,time
from app import store
tid=sys.argv[1]
for _ in range(50):
    if store.get(tid)['status']=='failed': break
    time.sleep(.1)
else: raise SystemExit('模拟任务未及时结束')
assert store.update(tid,'running','模拟分段处理中')
assert store.draft_write(tid,'plan',0,titles=['背景','建议']) is None
assert store.draft_write(tid,'section',0,position=1,content='已保存的虚构章节') is None
root=store.create('version-restart-root','虚构资料')['id']
store.update(root,'running','处理中')
assert store.finish(root,'版本恢复检查原文',0)
child=store.create_followup(root,'修改')['id']
store.update(child,'running','处理中')
assert store.finish(child,'版本恢复检查新文',0)
restored=store.restore(child,root)
from pathlib import Path
Path(store.connection().execute('PRAGMA database_list').fetchone()[2]).with_suffix('.version').write_text(restored['id'])
from app import library
from app.office import OfficeDocument
source=library.upload('重启资料.txt','资料原件唯一标记'.encode())
office_id=store.create('办公重启测试','',[source['id']])['id']
store.update(office_id,'running','处理中')
assert library.finish_office(office_id,OfficeDocument.model_validate({'kind':'xlsx','title':'重启清单','sheets':[{'name':'需求','rows':[['事项'],['预算未定']]}]}),0)
Path(store.connection().execute('PRAGMA database_list').fetchone()[2]).with_suffix('.office').write_text(office_id)
from app import review
q=store.create('澄清重启测试','虚构资料')['id'];store.update(q,'running','处理中')
assert store.wait_for_input(q,'本期只读还是可编辑？推荐只读。',0,[{'question':'只读还是编辑','recommendation':'只读','reason':'范围'}])
a=store.create_followup(q,'按推荐，只读')['id'];store.update(a,'running','处理中')
assert store.finish(a,'只读草稿',0,['建议按负责人筛选'])
review.confirm(a,review.get(a)['revision'])
n=store.create_followup(a,'只改标题')['id']
Path(store.connection().execute('PRAGMA database_list').fetchone()[2]).with_suffix('.review').write_text(__import__('json').dumps([q,a,n]))
from app import office_sessions
from io import BytesIO
from docx import Document
native_root=store.create('原文件会话重启测试','虚构资料')['id'];store.update(native_root,'running','处理中');assert store.finish(native_root,'# 原稿',0)
s1=office_sessions.create(native_root);s2=office_sessions.create(native_root)
doc=Document();doc.add_paragraph('虚构原文件内容');doc.add_table(rows=1,cols=1).cell(0,0).text='虚构表格';buf=BytesIO();doc.save(buf);native_bytes=buf.getvalue()
saved=office_sessions.finish(s1['id'],native_bytes);conflict=office_sessions.finish(s2['id'],native_bytes)
assert saved['status']=='saved' and conflict['status']=='conflict'
Path(store.connection().execute('PRAGMA database_list').fetchone()[2]).with_suffix('.native').write_text(__import__('json').dumps([s1['id'],s2['id'],saved['task_id'],__import__('hashlib').sha256(native_bytes).hexdigest()]))
print('已保存原文件版本和冲突会话恢复数据')
print('已保存临时章节草稿、恢复版本、文件资料和结构化办公成果；另存澄清问答与用户确认状态')
PYCODE
)
kill "$PID"; wait "$PID" || true; PID=""; echo '服务已停止'
start
curl -fsS "http://127.0.0.1:$PORT/api/v1/tasks/$ID" | "$ROOT/backend/.venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); assert d["goal"]=="restart-check-unique" and d["material"]=="temporary" and d["status"]=="interrupted" and d["draft"][0]["content"]=="已保存的虚构章节" and d["draft"][1]["content"] is None; print("重启后任务、资料和章节草稿读回成功")'

(cd "$ROOT/backend" && AGENT_DB_PATH="$TMPDIR_AGENT/data.sqlite" .venv/bin/python - <<'PYCODE'
from pathlib import Path
from app import store
with store.connection() as db:
    tid=Path(db.execute('PRAGMA database_list').fetchone()[2]).with_suffix('.version').read_text()
retried, created = store.create_once('restart-check-unique', 'temporary', request_id='restart-key')
assert not created and retried['status']=='interrupted'
print('重启后相同提交标识找回原任务，没有创建或重新调度')
assert store.get(tid)['result']=='版本恢复检查原文'
assert len(store.versions(tid))==3
assert store.context_link(tid)
print('重启后恢复版本、原稿和版本关系读回成功')
from app import library
with store.connection() as db:
    office_id=Path(db.execute('PRAGMA database_list').fetchone()[2]).with_suffix('.office').read_text()
sources=library.sources(office_id)
assert len(sources)==1
assert library.get(sources[0]['id'])['content']=='资料原件唯一标记'.encode()
assert library.office(office_id)['sheets'][0]['rows'][1][0]=='预算未定'
print('重启后资料原件、来源关联和Excel结构读回成功')
from app import review
with store.connection() as db:
    ids=__import__('json').loads(Path(db.execute('PRAGMA database_list').fetchone()[2]).with_suffix('.review').read_text())
    assert db.execute('SELECT count(*) FROM task_clarifications').fetchone()[0]==1
q,a,n=ids
assert store.get(q)['status']=='waiting'
assert store.task_history(n)[0]['question']=='本期只读还是可编辑？推荐只读。'
assert store.task_history(n)[1]['goal']=='按推荐，只读'
assert review.get(a)['status']=='confirmed'
assert review.get(n)['status']=='pending'
assert review.get(n)['items']==[]
print('重启后澄清问题、原始回答、旧版人工确认与新版待确认状态恢复成功')
from app import office_sessions
with store.connection() as db:
    saved_sid,conflict_sid,native_id,expected_hash=__import__('json').loads(Path(db.execute('PRAGMA database_list').fetchone()[2]).with_suffix('.native').read_text())
assert office_sessions.get(saved_sid)['result_id']==native_id
assert __import__('hashlib').sha256(library.native_office(native_id)['content']).hexdigest()==expected_hash
assert __import__('hashlib').sha256(office_sessions.get(conflict_sid)['recovery']).hexdigest()==expected_hash
print('重启后原文件版本及冲突会话恢复数据读回成功')

PYCODE
)
