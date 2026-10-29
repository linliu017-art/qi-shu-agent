"""Small real-model smoke test using a synthetic attached file and isolated database."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, library, store

assert os.environ.get('EVAL_APPROVED') == 'yes'
calls = []
Original = agent.httpx.Client


class Observed(Original):
    def post(self, *args, **kwargs):
        response = super().post(*args, **kwargs)
        if response.is_success:
            for choice in response.json().get('choices', []):
                for call in choice.get('message', {}).get('tool_calls', []):
                    calls.append(call.get('function', {}).get('name'))
        return response


agent.httpx.Client = Observed
with TemporaryDirectory(prefix='qi-shu-file-smoke-') as tmp:
    os.environ['AGENT_DB_PATH'] = str(Path(tmp) / 'agent.sqlite')
    store.init()
    source = library.upload('虚构访谈.txt', '虚构访谈：希望集中查看任务负责人。甲说首批产品部，乙说首批项目管理部，两者尚未统一。是否能修改负责人也未决定。'.encode())
    task = store.create('根据附件写简短PRD，影响核心范围的冲突先向我追问。', '', [source['id']])
    agent.run(task['id'])
    result = store.get(task['id'])
    report = {'status': result['status'], 'progress': result['progress'], 'result': result['result'],
              'tool_calls': calls, 'usage': store.task_usage(task['id']), 'cache': store.task_cache_usage(task['id'])}
    report['read_before_asking'] = 'read_source' in calls and ('ask_user' not in calls or calls.index('read_source') < calls.index('ask_user'))
    path = ROOT / 'data/evaluation' / ('attached-clarification-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('状态:', report['status'], '先读附件:', report['read_before_asking'], '调用:', calls, '报告:', path, flush=True)
    if result['status'] != 'waiting' or not report['read_before_asking']:
        sys.exit(1)
