"""Bounded real-model smoke on synthetic data, isolated from user tasks."""
import os, sys, json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, store
assert os.environ.get('EVAL_APPROVED') == 'yes'
trace = []
all_tools = []
Original = agent.httpx.Client
class Observed(Original):
    def post(self, *args, **kwargs):
        response = super().post(*args, **kwargs)
        if response.is_success:
            for choice in response.json().get('choices', []):
                for call in choice.get('message', {}).get('tool_calls', []):
                    fn = call.get('function', {})
                    all_tools.append(fn.get('name'))
                    if fn.get('name') == 'read_business_guide':
                        trace.append(json.loads(fn['arguments']))
        return response
agent.httpx.Client = Observed
rows = []
with TemporaryDirectory(prefix='qi-shu-skill-check-') as tmp:
    os.environ['AGENT_DB_PATH'] = str(Path(tmp) / 'agent.sqlite')
    store.init()
    for gid, title in [('prd','PRD'), ('initiation','立项报告'), ('competitor','竞品对比')]:
        if os.environ.get('GUIDE_CASE') and os.environ['GUIDE_CASE'] != gid:
            continue
        trace.clear()
        all_tools.clear()
        task = store.create(f'先读取{gid}业务指引及其中一个参考模板，依据虚构资料写一份简短{title}草稿并保存。只基于现有资料，缺失信息标待确认，本轮不追问、不联网。', '虚构资料：产品A面向项目经理，支持集中查看任务负责人；产品B面向个人用户，支持个人待办。内部希望减少任务遗漏，目前没有量化数据，预算和上线日期未定。')
        agent.run(task['id'])
        result = store.get(task['id'])
        rows.append({'guide':gid,'status':result['status'],'progress':result['progress'],'guide_calls':trace[:], 'tool_calls':all_tools[:], 'reference_loaded':any(x.get('guide_id') == gid for x in trace), 'result':result['result'], 'usage':store.task_usage(task['id'])})
        print(gid, result['status'], rows[-1]['reference_loaded'], flush=True)
path = ROOT / 'data/evaluation' / ('skill-guides-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
path.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(path)
if not all(r['status']=='completed' and r['reference_loaded'] for r in rows):
    sys.exit(1)
