import json
from app.agent import compact_for_budget, compact_tool_schemas, TOOLS, OFFICE_TOOLS


def test_budget_compaction_retains_instructions_and_complete_latest_exchange():
    messages=[{'role':'system','content':'规则'},{'role':'user','content':'任务'},
              {'role':'assistant','tool_calls':[{'id':'old'}]},{'role':'tool','tool_call_id':'old','content':'可重读'},
              {'role':'user','content':'补充'}, {'role':'assistant','tool_calls':[{'id':'new'}]},
              {'role':'tool','tool_call_id':'new','content':'最近结果'}]
    assert compact_for_budget(messages)==[messages[0],messages[1],messages[4],messages[5],messages[6]]


def test_schema_compaction_preserves_tools_and_schema_names_and_constraints():
    sample=[{'type':'function','function':{'name':'sample','description':'说明','parameters':{'type':'object','properties':{'description':{'type':'string','description':'解释','maxLength':8}},'required':['description']}}}]
    compact=compact_tool_schemas(sample)
    assert compact[0]['function']['parameters']['properties']['description']=={'type':'string','maxLength':8}
    assert compact[0]['function']['parameters']['required']==['description']
    full=TOOLS+OFFICE_TOOLS
    assert [v['function']['name'] for v in compact_tool_schemas(full)]==[v['function']['name'] for v in full]
    assert len(json.dumps(compact_tool_schemas(full),ensure_ascii=False).encode())<len(json.dumps(full,ensure_ascii=False).encode())
