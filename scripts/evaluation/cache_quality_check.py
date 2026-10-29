"""Two approved synthetic edit tasks; compare quality and provider cache reports."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, store  # noqa: E402


def main():
    if sys.argv[1:] != ['--execute'] or os.environ.get('EVAL_APPROVED') != 'yes':
        raise SystemExit('未执行：须经用户确认真实评测费用并显式启用。')
    if not all(os.environ.get(k) for k in ('MODEL_API_KEY', 'MODEL_BASE_URL', 'MODEL_NAME')):
        raise SystemExit('未执行：模型配置不完整。')
    sections = ['# 项目资料整理\n\n本文为虚构测试资料。\n']
    for n in range(1, 61):
        sections.append(f'## 工作环节 {n}\n\n这是第 {n} 个虚构工作环节，记录负责人应核对项目状态、工作依据和待确认事项。当前资料没有提供具体日期，不应凭空补充。此段仅用于验证未修改内容是否完整保留。\n')
    sections.append('## 专项说明\n\n预算状态：尚待确认。\n上线时间：尚待确认。\n\n## 附录\n\n附件材料均为虚构测试内容。\n')
    original = '\n'.join(sections)
    cases = [
        {'id':'budget', 'instruction':'请只将“预算状态：尚待确认。”改为“预算状态：尚未确定。”，其他内容全部保持原样。', 'before':'预算状态：尚待确认。', 'after':'预算状态：尚未确定。'},
        {'id':'schedule', 'instruction':'请只将“上线时间：尚待确认。”改为“上线时间：尚未确定。”，其他内容全部保持原样。', 'before':'上线时间：尚待确认。', 'after':'上线时间：尚未确定。'},
    ]
    rows = []
    with TemporaryDirectory(prefix='qi-shu-cache-eval-') as tmp:
        os.environ['AGENT_DB_PATH'] = str(Path(tmp) / 'eval.sqlite')
        store.init()
        parent = store.create('整理项目工作与专项说明', '虚构资料：项目工作和专项说明。')
        store.update(parent['id'], 'running', '处理中')
        if not store.finish(parent['id'], original, 0):
            raise RuntimeError('无法准备隔离的虚构成果')
        for case in cases:
            task = store.create_followup(parent['id'], case['instruction'])
            started = time.monotonic()
            agent.run(task['id'])
            result = store.get(task['id'])
            expected = original.replace(case['before'], case['after'])
            rows.append({'case':case['id'], 'status':result['status'], 'progress':result['progress'], 'seconds':round(time.monotonic()-started,2), 'matches_expected':result['result']==expected if result['status']=='completed' else False, 'target_changed':case['after'] in result['result'] if result['status']=='completed' else False, 'usage':store.task_usage(task['id']), 'cache':store.task_cache_usage(task['id'])})
            print(f"{case['id']}：{result['status']}，耗时 {rows[-1]['seconds']} 秒", flush=True)
    outdir = ROOT/'data'/'evaluation'
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir/f"context-cache-quality-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps({'model':os.environ['MODEL_NAME'], 'original_characters':len(original), 'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'评测记录已保存：{path}',flush=True)


if __name__ == '__main__':
    main()
