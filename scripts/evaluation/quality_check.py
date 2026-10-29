"""Fixed synthetic quality corpus. Metrics are evidence, not semantic pass scores."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, store, library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, choices=['baseline', 'after'])
    parser.add_argument('--case', dest='case_id', help='Optional single case; dependent cases still require their parent')
    args = parser.parse_args()
    if os.environ.get('EVAL_APPROVED') != 'yes':
        raise SystemExit('Set EVAL_APPROVED=yes after authorizing real-model costs.')
    cases_path = Path(__file__).with_name('quality_cases.json')
    cases = json.loads(cases_path.read_text())
    if args.case_id:
        cases = [case for case in cases if case['id'] == args.case_id]
        if not cases:
            raise SystemExit('Unknown case id')
    fingerprint_paths = [ROOT/'backend/app/agent.py', ROOT/'backend/app/guides.py',
                         *sorted((ROOT/'backend/app/prompts').glob('*'))]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = ROOT/'data/evaluation'/f'quality-{args.label}-{stamp}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'label': args.label, 'utc': stamp, 'model': os.environ.get('MODEL_NAME'),
              'selected_cases': [case['id'] for case in cases],
              'dataset_sha256': hashlib.sha256(cases_path.read_bytes()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in fingerprint_paths},
              'actual_charge': None, 'charge_note': '未获取供应商账单；按实报token与缓存用量记录成本依据，不编造实际费用。',
              'semantic_review': '待逐例核查；automated_checks仅检查可确定的机械属性', 'rows': []}
    trace = []
    original = agent.httpx.Client
    class Observed(original):
        def post(self, *a, **kw):
            response = super().post(*a, **kw)
            if response.is_success:
                for choice in response.json().get('choices', []):
                    for call in choice.get('message', {}).get('tool_calls', []):
                        fn = call.get('function', {})
                        item = {'name': fn.get('name')}
                        if fn.get('name', '').startswith('read_'):
                            # Fixed synthetic inputs only; never record arbitrary model write arguments.
                            try:
                                item['read_args'] = json.loads(fn.get('arguments', '{}'))
                            except ValueError:
                                item['invalid_arguments'] = True
                        trace.append(item)
            return response
    agent.httpx.Client = Observed
    try:
        with TemporaryDirectory(prefix='qi-shu-quality-') as tmp:
            os.environ['AGENT_DB_PATH'] = str(Path(tmp)/'agent.sqlite')
            store.init()
            results = {}
            for case in cases:
                parent = results.get(case.get('parent'))
                if case.get('parent') and (not parent or parent['status'] != 'completed'):
                    report['rows'].append({'case_id': case['id'], 'status': 'blocked', 'reason': '上一轮未完成，不能伪造前置成果', 'case': case})
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    continue
                sources = []
                if parent:
                    task = store.create_followup(parent['id'], case['goal'])
                elif case.get('seed'):
                    seed = store.create('虚构已有成果，供局部修改验证', case['material'])
                    store.update(seed['id'], 'completed', '测试夹具，非模型生成', case['seed'])
                    parent = store.get(seed['id'])
                    task = store.create_followup(seed['id'], case['goal'])
                else:
                    sources = [library.upload(file['name'], file['text'].encode()) for file in case.get('files', [])]
                    task = store.create(case['goal'], case.get('material', ''), [s['id'] for s in sources])
                trace.clear()
                started = time.monotonic()
                agent.run(task['id'])
                elapsed = round(time.monotonic() - started, 2)
                result = store.get(task['id'])
                results[case['id']] = result
                reads = Counter(json.dumps(x, sort_keys=True) for x in trace if x['name'].startswith('read_'))
                checks = {'saved_nonempty': result['status']=='completed' and bool(result['result'])}
                if parent:
                    checks['parent_unchanged'] = store.get(parent['id'])['result'] == parent['result']
                    if case['id']=='edit-owner':
                        before = parent['result'].splitlines(); after = result['result'].splitlines()
                        checks['non_target_lines_unchanged'] = len(before)==len(after) and before[:1]+before[2:]==after[:1]+after[2:]
                        checks['owner_corrected'] = len(after)>1 and '李四' in after[1] and '更正' in after[1]
                    else:
                        checks['exact_replacement'] = result['result'] == parent['result'].replace('备注：先试点。', '备注：先完成需求确认。')
                report['rows'].append({'case_id':case['id'], 'case':case, 'sources':sources,
                    'status':result['status'], 'progress':result['progress'], 'result':result['result'],
                    'seconds':elapsed, 'tool_calls':trace[:], 'duplicate_read_requests':sum(n-1 for n in reads.values()),
                    'usage':store.task_usage(task['id']), 'cache':store.task_cache_usage(task['id']), 'automated_checks':checks})
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(case['id'], result['status'], elapsed, checks, flush=True)
    finally:
        agent.httpx.Client = original
    print(output, flush=True)
    return 0 if all(row['status']=='completed' and all(row.get('automated_checks',{}).values()) for row in report['rows']) else 1

if __name__ == '__main__':
    raise SystemExit(main())
