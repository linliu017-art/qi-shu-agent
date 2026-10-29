import os,sys,json,time
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import store,library,agent
from app.office import OfficeDocument
assert os.environ.get('EVAL_APPROVED')=='yes'
rows=[]
cases=[({'kind':'xlsx','title':'负责人清单','sheets':[{'name':'需求','rows':[['事项','负责人'],['试用','张三'],['原文摘录','负责人张三']]}]},'只把工作表“需求”B2单元格的张三改为李四；B3原文摘录及其他内容逐字保留。',('sheets',0,'rows',1,1)),({'kind':'pptx','title':'试用汇报','slides':[{'title':'试用负责人','body':['负责人张三','预算未定']},{'title':'待确认','body':['上线时间未定']}]},'只把第1页第1条正文“负责人张三”改为“负责人李四”，其他所有内容不变。',('slides',0,'body',0))]
trace=[]
Original=agent.httpx.Client
class Observed(Original):
 def post(self,*a,**kw):
  r=super().post(*a,**kw)
  if r.is_success:
   for c in r.json().get('choices',[]):trace.extend(t.get('function',{}).get('name') for t in c.get('message',{}).get('tool_calls',[]))
  return r
agent.httpx.Client=Observed
with TemporaryDirectory(prefix='qi-shu-office-patch-') as tmp:
 os.environ['AGENT_DB_PATH']=str(Path(tmp)/'data.sqlite');store.init()
 for data,goal,path in cases:
  document=OfficeDocument.model_validate(data);root=store.create('整理试用信息','虚构资料')['id'];store.update(root,'running','prepare');library.finish_office(root,document,0)
  task=store.create_followup(root,goal);trace.clear();start=time.monotonic();agent.run(task['id']);result=store.get(task['id']);actual=library.office(task['id']);expected=document.model_dump();node=expected
  for key in path[:-1]:node=node[key]
  node[path[-1]]=node[path[-1]].replace('张三','李四')
  rows.append({'kind':document.kind,'status':result['status'],'tool_calls':trace[:],'exact_match':actual==expected,'original_unchanged':library.office(root)==document.model_dump(),'seconds':round(time.monotonic()-start,2),'usage':store.task_usage(task['id']),'document':actual})
  print(document.kind,result['status'],actual==expected,flush=True)
path=ROOT/'data/evaluation'/('office-patch-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json');path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(path)
