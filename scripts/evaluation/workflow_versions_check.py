import os,sys,json,time
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import store,agent
assert os.environ.get('EVAL_APPROVED')=='yes'
rows=[]
with TemporaryDirectory(prefix='qi-shu-versions-') as tmp:
 os.environ['AGENT_DB_PATH']=str(Path(tmp)/'test.sqlite');store.init()
 original='# 客户需求\n\n预算：未确定。\n上线时间：未确定。\n负责人：张三。\n\n## 资料事实\n使用 Excel 跟踪任务，产品部先试用。'
 root=store.create('根据资料整理客户需求，不编造预算和日期。','虚构资料：使用 Excel 跟踪任务，产品部先试用。预算及日期未知。负责人张三。')['id']
 store.update(root,'running','测试准备');store.finish(root,original,0)
 current=root;expected=original
 for before,after in [('负责人：张三。','负责人：李四。'),('预算：未确定。','预算：待客户确认。')]:
  task=store.create_followup(current,f'仅将“{before}”替换为“{after}”，此前修改和其余内容逐字保留。')
  started=time.monotonic();agent.run(task['id']);result=store.get(task['id']);expected=expected.replace(before,after)
  rows.append({'case':'连续局部修改','status':result['status'],'exact_match':result['result']==expected,'seconds':round(time.monotonic()-started,2),'usage':store.task_usage(task['id']),'result':result['result']})
  print(rows[-1]['case'],result['status'],rows[-1]['exact_match'],flush=True)
  if result['status']!='completed':break
  current=task['id']
 restored=store.restore(current,root)
 rows.append({'case':'恢复最初版本','exact_match':bool(restored and restored['result']==original),'original_unchanged':store.get(root)['result']==original})
 task=store.create('整理两份访谈的共识、冲突和待确认问题，不选择一个冲突答案当事实；不编造预算与日期，300字以内。','虚构访谈 A：第一批仅产品部试用，使用人数20人。虚构访谈 B：第一批产品部和销售部试用，人数50人。两人都说预算和上线日期未定。')
 started=time.monotonic();agent.run(task['id']);result=store.get(task['id'])
 rows.append({'case':'冲突资料','status':result['status'],'seconds':round(time.monotonic()-started,2),'usage':store.task_usage(task['id']),'result':result['result']})
path=ROOT/'data/evaluation'/('workflow-versions-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(path)
