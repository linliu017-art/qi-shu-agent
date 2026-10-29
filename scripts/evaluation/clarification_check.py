"""Real synthetic clarification -> partial answer -> draft -> explicit review."""
import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import agent, store, review
assert os.environ.get('EVAL_APPROVED')=='yes'
report={'model':os.environ.get('MODEL_NAME'),'rows':[],'human_review_actions':[]}
path=ROOT/'data/evaluation'/('clarification-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
trace=[]
Original=agent.httpx.Client
class Observed(Original):
 def post(self,*args,**kwargs):
  response=super().post(*args,**kwargs)
  if response.is_success:
   for choice in response.json().get('choices',[]):
    for call in choice.get('message',{}).get('tool_calls',[]):
     fn=call.get('function',{});entry={'name':fn.get('name')}
     if fn.get('name')=='ask_user': entry['questions']=json.loads(fn.get('arguments','{}'))
     if fn.get('name') in ('save_artifact','plan_sections'):
      try:
       params=json.loads(fn.get('arguments','{}'));entry['answer_evidence']={key:params.get(key) for key in ('answered_questions','defer_quote')}
      except ValueError:entry['invalid_json']=True
     trace.append(entry)
  return response
agent.httpx.Client=Observed

def run(case,goal,material='',parent=None,expected='completed'):
 task=store.create_followup(parent,goal) if parent else store.create(goal,material)
 if not task:
  report['rows'].append({'case':case,'status':'blocked','reason':'父任务无法继续'});return None
 trace.clear();start=time.monotonic();agent.run(task['id']);result=store.get(task['id'])
 row={'case':case,'goal':goal,'material':material,'status':result['status'],'expected':expected,'status_match':result['status']==expected,'progress':result['progress'],'result':result['result'],'review':review.get(task['id']),'tool_calls':trace[:],'seconds':round(time.monotonic()-start,2),'usage':store.task_usage(task['id']),'cache':store.task_cache_usage(task['id'])}
 report['rows'].append(row);path.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(case,result['status'],row['status_match'],flush=True)
 return task['id']

with TemporaryDirectory(prefix='qi-shu-clarification-') as tmp:
 os.environ['AGENT_DB_PATH']=str(Path(tmp)/'agent.sqlite');store.init()
 first=run('critical-before-draft','根据资料写一份供评审的简短PRD草稿。','虚构访谈：项目经理希望集中查看任务负责人。记录甲说首批产品部，记录乙说首批项目管理部，尚无统一结论。本期是否允许修改负责人尚未决定。预算和日期未知。',expected='waiting')
 if first and store.get(first)['status']=='waiting':
  second=run('partial-answer','首批统一为产品部。',parent=first,expected='waiting')
  if second and store.get(second)['status']=='waiting':
   draft=run('answer-and-draft','本期只覆盖集中查看任务负责人这一项能力，不含其他任务管理功能。本期只读，不允许修改负责人。数据可见范围沿用当前用户已有权限，不扩大。其余可选细节按你推荐先写成建议，生成简短草稿。',parent=second)
   if draft and store.get(draft)['status']=='completed':
    before=review.get(draft);confirmed=review.confirm(draft,before['revision']);store.init()
    report['human_review_actions'].append({'action':'explicit_confirm_in_test','task_id':draft,'before':before,'after':review.get(draft),'persisted':review.get(draft)==confirmed})
    edited=run('edit-after-confirm','仅把标题里的“PRD”改为“需求说明”，其他正文逐字保留。不要再问已确认的试点或只读范围。',parent=draft)
    if edited and store.get(edited)['status']=='completed':
     old=store.get(draft)['result'];new=store.get(edited)['result'];report['human_review_actions'].append({'action':'new_version_requires_review','old_confirmed':review.get(draft)['status']=='confirmed','new_pending':review.get(edited)['status']=='pending','body_unchanged':old.split('\n',1)[-1]==new.split('\n',1)[-1]})
 run('explicit-assumption-draft','先按假设写简短PRD草稿，本轮不追问。试点推荐产品部；权限推荐只读。把假设和筛选建议列为待确认。','虚构资料：项目经理希望集中查看负责人。试点和权限未定，预算未知。')
 run('budget-required','编制一份可供审批的项目预算方案。','虚构资料：要建设一个内部任务工作台。预算上限、费用范围、使用人数和部署方式均未确定。',expected='waiting')
 run('optional-detail-not-blocking','根据资料写简短PRD草稿，可选细节给建议。','虚构已确认需求：首批产品部项目经理试用，只读查看任务负责人，不允许修改，使用现有内网登录，仅可看本人项目。是否增加筛选、排序未决定，预算和日期尚未确定。')
path.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(path)
if len(report['rows'])!=7 or not all(r.get('status_match') for r in report['rows']):sys.exit(1)
