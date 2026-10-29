"""Resume saved synthetic chapters in a fresh isolated database; no user data."""
import json
import os
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import agent,store

def main():
    if sys.argv[1:]!=['--execute'] or os.environ.get('EVAL_APPROVED')!='yes':
        raise SystemExit('未执行：真实测试需显式启用。')
    files=sorted((ROOT/'data'/'evaluation').glob('long-workflow-*.json'))
    if not files: raise SystemExit('未找到前次测试记录。')
    previous=json.loads(files[-1].read_text(encoding='utf-8'))
    resumes=sorted((ROOT/'data'/'evaluation').glob('resume-workflow-*.json'))
    if resumes:
        latest=json.loads(resumes[-1].read_text(encoding='utf-8'))
        previous['sections']=latest['sections']
        previous['usage']=latest['usage']
    if not previous['sections']: raise SystemExit('前次没有保存章节。')
    with TemporaryDirectory(prefix='qi-shu-resume-eval-') as temp:
        os.environ['AGENT_DB_PATH']=str(Path(temp)/'test.sqlite')
        store.init(); task=store.create(previous['goal'],previous['material'])
        store.update(task['id'],'running','正在恢复')
        if store.draft_write(task['id'],'plan',0,titles=[s['title'] for s in previous['sections']]): raise RuntimeError('无法恢复计划')
        for s in previous['sections']:
            if s['content'] is not None and store.draft_write(task['id'],'section',0,position=s['position'],content=s['content']): raise RuntimeError('无法恢复章节')
        store.record_usage(task['id'],previous['usage']['input_tokens'],previous['usage']['output_tokens'])
        store.update(task['id'],'failed','等待继续')
        if not store.resume(task['id']): raise RuntimeError('无法继续')
        before=store.draft(task['id']); start=time.monotonic(); agent.run(task['id']); final=store.get(task['id']);after=store.draft(task['id']) or []
        report={'source':files[-1].name,'status':final['status'],'progress':final['progress'],'result':final['result'],'sections':after,'preserved':all(x['content'] is None or any(y['position']==x['position'] and y['content']==x['content'] for y in after) for x in before),'usage':store.task_usage(task['id']),'seconds':round(time.monotonic()-start,2)}
    out=ROOT/'data'/'evaluation'/f"resume-workflow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"结果：{report['status']}；{report['progress']}；已保存章节保留={report['preserved']}；记录：{out}",flush=True)
if __name__=='__main__':main()
