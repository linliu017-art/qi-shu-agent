"""Run one authorized synthetic long-document task, inject a local interruption, then resume."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, store  # noqa: E402


def main():
    if sys.argv[1:] != ['--execute'] or os.environ.get('EVAL_APPROVED') != 'yes':
        raise SystemExit('未执行：真实评测需显式启用。')
    if not all(os.environ.get(k) for k in ('MODEL_API_KEY','MODEL_BASE_URL','MODEL_NAME')):
        raise SystemExit('未执行：模型配置不完整。')
    goal = '请依据材料写一篇分章节的建设方案，包含背景、建设目标、实施建议三个章节，每章尽量写具体。请逐章写作并保存进度，全部完成后合并。没有证据的内容标记为建议或待确认。'
    material = '虚构项目：某团队使用多份表格跟踪工作，常遗漏负责人，希望统一查看任务状态。第一批由产品和项目管理部门试用，规模未定，预算和上线时间均未确定。希望保留人工确认，不自动对外发送消息。'
    with TemporaryDirectory(prefix='qi-shu-long-eval-') as temp:
        os.environ['AGENT_DB_PATH'] = str(Path(temp)/'test.sqlite')
        store.init()
        task=store.create(goal,material)
        real_client=httpx.Client
        injected={'done':False}
        tool_trace=[]
        class Client:
            def __init__(self,**kwargs): self.inner=real_client(**kwargs)
            def __enter__(self): self.inner.__enter__(); return self
            def __exit__(self,*args): return self.inner.__exit__(*args)
            def post(self,*args,**kwargs):
                draft=store.draft(task['id'])
                if not injected['done'] and draft and any(section['content'] for section in draft):
                    injected['done']=True
                    raise httpx.ReadTimeout('模拟网络中断')
                response=self.inner.post(*args,**kwargs)
                try:
                    raw=response.json()
                    choices=raw.get('choices') or []
                    message=(choices[0].get('message') or {}) if choices else {}
                    calls=message.get('tool_calls') or []
                    tool_trace.append({'status':response.status_code,'finish_reason':choices[0].get('finish_reason') if choices else None,'tools':[call.get('function',{}).get('name') for call in calls]})
                except (ValueError,TypeError,KeyError):
                    tool_trace.append({'status':response.status_code,'invalid_json':True})
                return response
        agent.httpx.Client=Client
        start=time.monotonic()
        agent.run(task['id'])
        first=store.get(task['id'])
        saved=store.draft(task['id'])
        saved_before=[{'position':x['position'],'title':x['title'],'content':x['content']} for x in (saved or [])]
        resumed=False
        if injected['done'] and first['status']=='failed' and store.resume(task['id']):
            resumed=True
            agent.run(task['id'])
        final=store.get(task['id'])
        after=store.draft(task['id']) or []
        preserved=all(x['content'] is None or any(y['position']==x['position'] and y['content']==x['content'] for y in after) for x in saved_before)
        report={'model':os.environ['MODEL_NAME'],'tool_trace':tool_trace,'goal':goal,'material':material,'interruption_simulated':injected['done'],'first_status':first['status'],'saved_before':saved_before,'resume_started':resumed,'final_status':final['status'],'final_progress':final['progress'],'result':final['result'],'sections':after,'saved_sections_preserved':preserved,'usage':store.task_usage(task['id']),'cache':store.task_cache_usage(task['id']),'seconds':round(time.monotonic()-start,2)}
    out=ROOT/'data'/'evaluation'
    out.mkdir(parents=True,exist_ok=True)
    path=out/f"long-workflow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"测试记录：{path}; 中断模拟={injected['done']}; 初次={first['status']}; 恢复={resumed}; 最终={final['status']}; 已保存内容保留={preserved}",flush=True)


if __name__=='__main__': main()
