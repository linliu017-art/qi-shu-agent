import json
import os
from pathlib import Path
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, StringConstraints, model_validator
from typing import Literal, Annotated
from . import store, library, review
from .office import OfficeDocument, OfficeChanges, apply_office_changes
from .guides import read_guide


class ToolFunction(BaseModel):
    name: Literal["read_material", "read_previous_result", "read_task_history", "find_previous_result", "save_artifact", "apply_edits", "ask_user", "plan_sections", "save_section", "finish_sections", "read_draft", "read_source", "read_business_guide", "save_office", "read_previous_office", "apply_office_edits"]
    arguments: str = Field(max_length=120000)


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"]
    function: ToolFunction


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["assistant"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=8)


class ModelChoice(BaseModel):
    message: ModelMessage


class ModelUsage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    prompt_cache_hit_tokens: int | None = Field(default=None, ge=0)
    prompt_cache_miss_tokens: int | None = Field(default=None, ge=0)


def cache_breakdown(usage):
    hit = usage.prompt_cache_hit_tokens
    miss = usage.prompt_cache_miss_tokens
    if hit is None or miss is None or hit + miss != usage.prompt_tokens:
        return None, None
    return hit, miss


class ModelResponse(BaseModel):
    choices: list[ModelChoice] = Field(min_length=1)
    usage: ModelUsage


ReviewItems = list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]]


class AnswerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_index: int = Field(ge=1, le=3, description="紧邻上一轮追问的显示顺序，从1开始；不要沿用问题正文提及的历史编号")
    answer_quote: str = Field(min_length=1, max_length=1000)


class SaveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100000)
    review_items: ReviewItems | None = Field(default=None, max_length=8)
    answered_questions: list[AnswerEvidence] | None = Field(default=None, max_length=3)
    defer_quote: str | None = Field(default=None, min_length=1, max_length=1000)


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original: str = Field(min_length=1, max_length=20000)
    replacement: str = Field(max_length=20000)


class EditsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edits: list[Edit] = Field(min_length=1, max_length=10)


def apply_exact_edits(original_text, edits):
    spans = []
    for edit in edits:
        first = original_text.find(edit.original)
        if first < 0 or original_text.find(edit.original, first + 1) >= 0:
            raise ValueError("修改位置不存在或不唯一，请重新读取并提供更准确的原文")
        spans.append((first, first + len(edit.original), edit.replacement))
    spans.sort(key=lambda span: span[0])
    if any(spans[i][1] > spans[i+1][0] for i in range(len(spans)-1)):
        raise ValueError("修改位置重叠，请合并后重试")
    result = original_text
    for start, end, replacement in reversed(spans):
        result = result[:start] + replacement + result[end:]
    if not result or len(result) > 100000:
        raise ValueError("修改后的成果为空或超过保存限制")
    return result


class SectionPlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[str] = Field(min_length=2, max_length=12)
    review_items: ReviewItems | None = Field(default=None, max_length=8)
    answered_questions: list[AnswerEvidence] | None = Field(default=None, max_length=3)
    defer_quote: str | None = Field(default=None, min_length=1, max_length=1000)


class SectionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int = Field(ge=1, le=12)
    content: str = Field(min_length=1, max_length=7000)


class DraftReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int = Field(ge=1, le=12)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=3000, ge=1, le=3000)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    recommendation: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class QuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str | None = Field(default=None, min_length=1, max_length=5000)
    questions: list[ClarificationQuestion] | None = Field(default=None, min_length=1, max_length=3)

    @model_validator(mode='after')
    def exactly_one_format(self):
        if (self.question is None) == (self.questions is None):
            raise ValueError('请提供1至3个问题，不能混用问题格式')
        return self

    def render(self):
        if self.question is not None:
            return self.question
        return "\n\n".join(f"### {i}. {q.question}\n推荐：{q.recommendation}\n影响：{q.reason}" for i, q in enumerate(self.questions, 1))


# Keep parsing legacy responses; expose the structured contract to new model calls.
QUESTION_SCHEMA = QuestionArgs.model_json_schema()
QUESTION_SCHEMA['properties'].pop('question')
QUESTION_SCHEMA['required'] = ['questions']


class FindArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=1, max_length=100)


class ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=3000, ge=1, le=3000)


def page_text(text, offset, limit):
    if offset > len(text):
        raise ValueError("读取位置超出内容")
    end = min(offset + limit, len(text))
    return json.dumps({"text": text[offset:end], "offset": offset, "next_offset": end if end < len(text) else None, "total_characters": len(text), "complete": end == len(text)}, ensure_ascii=False)


def cited_page(text, offset, limit, source_id=None):
    """Keep legacy pagination and add an exact, Unicode-character citation range."""
    page = json.loads(page_text(text, offset, limit))
    label = source_id if source_id is not None else "粘贴资料"
    end = offset + len(page['text'])
    page.update(source_kind="file" if source_id is not None else "pasted",
                citation=f"[{label}，字符{offset}–{end}，左闭右开]",
                end_offset=end)
    return page


def compact_messages(messages):
    # Keep all user instructions and the two newest complete tool-call exchanges.
    assistants = [i for i, message in enumerate(messages) if message.get("role") == "assistant"]
    if len(assistants) <= 2:
        return messages
    cutoff = assistants[-2]
    return [message for i, message in enumerate(messages) if i >= cutoff or message.get("role") in ("system", "user")]


def compact_for_budget(messages):
    """Keep instructions and the latest complete tool exchange; old data can be reread."""
    assistants = [i for i, message in enumerate(messages) if message.get("role") == "assistant"]
    if not assistants:
        return messages
    cutoff = assistants[-1]
    return [message for i, message in enumerate(messages) if i >= cutoff or message.get("role") in ("system", "user")]


def compact_tool_schemas(tools):
    """Drop only JSON Schema annotations; retain every tool and validation constraint."""
    def strip(value):
        if isinstance(value, dict):
            return {k: ({name: strip(schema) for name, schema in v.items()} if k in ("properties", "$defs", "patternProperties") and isinstance(v, dict) else strip(v))
                    for k, v in value.items() if k not in ("title", "default", "description", "examples")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return [{**tool, "function": {**tool["function"], "parameters": strip(tool["function"]["parameters"])}} for tool in tools]




def clarification_memory(history):
    records = []
    for index, entry in enumerate(history):
        if entry.get('question') and index + 1 < len(history):
            records.append({'history_index': index, 'question': entry['question'], 'answer': history[index+1]['goal']})
        if entry.get('review'):
            records.append({'history_index': index, 'review': entry['review']})
    kept = []
    for record in reversed(records):
        candidate = [record] + kept
        if len(json.dumps(candidate, ensure_ascii=False)) > 6000:
            break
        kept = candidate
    return json.dumps({'records': kept, 'omitted': len(records)-len(kept), 'note': '有省略时先按需读历史，不得猜测答案或把未决项当已确认'}, ensure_ascii=False)


TOOLS = [
    {"type":"function","function":{"name":"plan_sections","description":"为长成果建立2至12个有序章节标题；计划保存后不可覆盖","parameters":SectionPlanArgs.model_json_schema()}},
    {"type":"function","function":{"name":"save_section","description":"按计划独立保存一个章节正文，不含章节标题；已保存章节不可覆盖","parameters":{"type":"object","properties":{"position":{"type":"integer","minimum":1,"maximum":12},"content":{"type":"string","minLength":1,"maxLength":7000}},"required":["position","content"],"additionalProperties":False}}},
    {"type":"function","function":{"name":"read_draft","description":"按位置分页读取已保存的章节草稿","parameters":{"type":"object","properties":{"position":{"type":"integer","minimum":1,"maximum":12},"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":3000}},"required":["position"],"additionalProperties":False}}},
    {"type":"function","function":{"name":"finish_sections","description":"所有章节均保存后按原计划合并为完整成果","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type": "function", "function": {"name": "ask_user", "description": "关键目标、范围、冲突或任务必要约束不清时，先读资料与已有问答，再提出1至3个问题，每个带推荐和影响，暂停等待。可选细节列入草稿review_items", "parameters": QUESTION_SCHEMA}},
    {"type": "function", "function": {"name": "read_material", "description": "按字符偏移分页读取用户提供的资料；next_offset 非空表示还有内容", "parameters": {"type": "object", "properties": {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 3000}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_task_history", "description": "按字符偏移分页读取本任务及其历史用户要求，不含成果全文", "parameters": {"type": "object", "properties": {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 3000}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_previous_result", "description": "按字符偏移分页读取本任务关联的上一版成果或待答问题；next_offset 非空表示还有内容", "parameters": {"type": "object", "properties": {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 3000}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "find_previous_result", "description": "在上一版成果中搜索关键词，返回最多10个字符偏移；再用 read_previous_result 读取原文", "parameters": {"type": "object", "properties": {"keyword": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["keyword"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "apply_edits", "description": "定向修改上一版成果，只替换唯一匹配的原文，保留未修改内容；先读取需修改的原文", "parameters": {"type": "object", "properties": {"edits": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "object", "properties": {"original": {"type": "string"}, "replacement": {"type": "string"}}, "required": ["original", "replacement"], "additionalProperties": False}}}, "required": ["edits"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "save_artifact", "description": "保存本任务文字草稿；review_items列需用户确认的建议或假设，最多8条。完成生成不等于用户已确认", "parameters": SaveArgs.model_json_schema()}},
]



class SourceReadArgs(ReadArgs):
    source_id: str = Field(min_length=1,max_length=64)


class OfficeSaveArgs(OfficeDocument):
    review_items: ReviewItems | None = Field(default=None, max_length=8)
    answered_questions: list[AnswerEvidence] | None = Field(default=None, max_length=3)
    defer_quote: str | None = Field(default=None, min_length=1, max_length=1000)


class GuideArgs(BaseModel):
    model_config=ConfigDict(extra="forbid")
    guide_id: str = Field(min_length=1,max_length=40)
    reference: str | None = Field(default=None, min_length=1, max_length=80)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=3000, ge=1, le=6000)


OFFICE_TOOLS = [
    {"type":"function","function":{"name":"apply_office_edits","description":"精确局部修改上一版办公成果，先read_previous_office。路径从0开始，例如sheets/0/rows/2/1、slides/0/body/0；提供原值和新值，程序保留所有其他内容。","parameters":OfficeChanges.model_json_schema()}},
    {"type":"function","function":{"name":"read_source","description":"分页读取本任务已关联的文件资料；结果带资料ID和原文位置，未关联资料不可访问","parameters":SourceReadArgs.model_json_schema()}},
    {"type":"function","function":{"name":"read_business_guide","description":"读取业务指引，可选requirements、proposal、review、competitor、initiation、prd、acceptance；按目标选择，不强制固定流程；返回references时可传reference名称分页读取本地skill模板，offset为字符位置","parameters":GuideArgs.model_json_schema()}},
    {"type":"function","function":{"name":"read_previous_office","description":"读取上一版Excel/PPT的完整可编辑结构，修改前必须读取","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"save_office","description":"保存最终Excel或PPT。xlsx使用sheets:[{name,rows:二维单元格数组}]；pptx使用slides:[{title,body:字符串数组}]。只用对应字段，不执行公式；保留来源引用。","parameters":OfficeSaveArgs.model_json_schema()}},
]


def run(tid):
    try:
        task = store.get(tid)
        if not task or not store.update(tid, "running", "正在准备任务"):
            return
        existing_draft = store.draft(tid)
        if existing_draft and all(section["content"] is not None for section in existing_draft):
            if store.draft_write(tid, 'finish', 0) is None:
                return
        key = os.getenv("MODEL_API_KEY", "")
        base = os.getenv("MODEL_BASE_URL", "")
        model = os.getenv("MODEL_NAME", "")
        if not key or not base or not model:
            store.update(tid, "failed", "模型未配置；真实调用须先确认费用")
            return
        if not base.startswith("https://"):
            store.update(tid, "failed", "模型地址必须使用 HTTPS")
            return
        prompt = (Path(__file__).parent / "prompts" / "work_agent_v1.txt").read_text(encoding="utf-8")
        link = store.context_link(tid)
        root_goal = store.original_goal(tid) if link else task["goal"]
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": "原始目标：" + root_goal}]
        if link:
            history = store.task_history(tid)
            messages[1]["content"] += "\n历史问答及人工确认（按原文记录，不要重复询问已答内容；有省略可read_task_history查看）：" + clarification_memory(history)
            previous_instructions = []
            for entry in history[:-1]:
                previous_instructions.append(entry["goal"])
                previous_instructions.extend(entry["corrections"])
            recent = "\n".join(previous_instructions[-3:])
            clipped = len(recent) > 2000
            recent = recent[-2000:]
            request = "近期历史要求：" + recent + "\n当前用户要求：" + task["goal"] + "\n这是对上一版成果或问题的继续处理，先按需调用 read_previous_result 读取。"
            if len(previous_instructions) > 3 or clipped:
                request += "\n历史要求已部分省略，可用 read_task_history 分页查看完整记录。"
            messages[1]["content"] += "\n" + request
        task_sources=library.sources(tid)
        messages[1]["content"] += "\n关联资料版本："+json.dumps(task_sources,ensure_ascii=False)+"。附件列表为空不代表没有粘贴资料。附件用read_source读取，不从文件名猜测内容。业务指引可按任务需要读取。"
        messages[1]["content"] += f"\n粘贴资料：{len(task['material'])}字符，" + ("可通过read_material读取。" if task['material'].strip() else "为空。")
        messages[1]["content"] += "本任务" + ("有上一版，可按修改需要读取。" if link else "没有上一版，不要调用read_previous_result或read_previous_office。")
        material_read = False
        source_read = False
        saved_draft = store.draft(tid)
        if saved_draft:
            overview = [{"position": item["position"], "title": item["title"], "saved": item["content"] is not None} for item in saved_draft]
            messages[1]["content"] += "\n已有章节计划及保存状态：" + json.dumps(overview, ensure_ascii=False) + "。继续未完成章节；必要时用 read_draft 查看已有内容，禁止重复覆盖。"
        last_correction = 0
        previous_office_read = False
        previous_read = False
        previous_ranges = []
        previous_read_full = False
        # A user-initiated resume starts a new bounded execution; historical usage remains stored.
        input_used = output_used = 0
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            for _ in range(16):
                current = store.get(tid)
                if not current or current["status"] != "running":
                    return
                for correction in store.corrections_since(tid, last_correction):
                    messages.append({"role": "user", "content": correction["content"]})
                    last_correction = correction["id"]
                # Preserve the request prefix for cache reuse until compaction is needed.
                if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > len(prompt.encode("utf-8")) + 6000:
                    messages = compact_messages(messages)
                request_input = {"model": model, "messages": messages, "tools": TOOLS + OFFICE_TOOLS}
                estimated_input = len(json.dumps(request_input, ensure_ascii=False).encode("utf-8")) + 2048
                if input_used + estimated_input > 50000:
                    messages = compact_for_budget(messages)
                    request_input = {"model": model, "messages": messages, "tools": compact_tool_schemas(TOOLS + OFFICE_TOOLS)}
                    estimated_input = len(json.dumps(request_input, ensure_ascii=False).encode("utf-8")) + 2048
                remaining_output = 10000 - output_used
                if input_used + estimated_input > 50000 or remaining_output < 1:
                    store.update(tid, "failed", "达到本任务模型用量限制，未完成")
                    return
                request_input["max_tokens"] = min(8192, remaining_output)
                response = None
                for attempt in range(2):
                    try:
                        response = client.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + key}, json=request_input)
                        response.raise_for_status()
                        break
                    except httpx.ConnectError:
                        if attempt == 1:
                            raise
                if response is None:
                    raise ValueError("empty response")
                raw = response.json()
                usage = ModelUsage.model_validate(raw.get("usage"))
                cache_hit, cache_miss = cache_breakdown(usage)
                store.record_usage(tid, usage.prompt_tokens, usage.completion_tokens, cache_hit, cache_miss)
                input_used += usage.prompt_tokens
                output_used += usage.completion_tokens
                if input_used > 50000 or output_used > 10000:
                    store.update(tid, "failed", "达到本任务模型用量限制，未完成")
                    return
                choices = raw.get("choices") or []
                if choices and choices[0].get("finish_reason") == "length":
                    store.update(tid, "failed", "模型输出超过单次长度限制，成果未保存")
                    return
                validated = ModelResponse.model_validate(raw)
                msg = validated.choices[0].message.model_dump(exclude_none=True)
                calls = msg["tool_calls"]
                messages.append(msg)
                for call in calls:
                    function = call["function"]
                    name = function["name"]
                    try:
                        args = json.loads(function["arguments"])
                    except json.JSONDecodeError:
                        call['function']['arguments'] = '{}'
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':'工具参数不是有效JSON，请修正JSON引号和转义后重试；尚未保存。'})
                        continue
                    if name in ("read_source", "read_business_guide", "read_previous_office", "save_office", "apply_office_edits"):
                        try:
                            if name == "read_source":
                                parsed=SourceReadArgs.model_validate(args)
                                source=library.read_source(tid,parsed.source_id)
                                page=cited_page(source['text'],parsed.offset,parsed.limit,source['id'])
                                source_read = source_read or bool(page['text'].strip())
                                output=json.dumps({**page, 'source_id':source['id'],'name':source['name'],'sha256':source['sha256']},ensure_ascii=False)
                            elif name == "read_business_guide":
                                parsed=GuideArgs.model_validate(args)
                                output=json.dumps(read_guide(**parsed.model_dump()),ensure_ascii=False)
                            elif name == "read_previous_office":
                                if args: raise ValueError('此工具不接受参数')
                                previous=library.office(link['parent_id']) if link else None
                                if not previous: raise ValueError('没有上一版结构化办公成果')
                                if len(json.dumps(previous,ensure_ascii=False))>24000:
                                    raise ValueError('上一版结构过长，当前请通过结构化编辑接口修改，不能只读取片段后覆盖')
                                previous_office_read=True
                                output=json.dumps(previous,ensure_ascii=False)
                            elif name == "apply_office_edits":
                                if not link or not previous_office_read: raise ValueError('请先读取上一版办公成果')
                                previous=library.office(link['parent_id'])
                                parsed=apply_office_changes(previous,OfficeChanges.model_validate(args))
                                if library.finish_office(tid,parsed,last_correction): return
                                output='用户有新补充或任务状态已变化，请先处理'
                            else:
                                office_args=OfficeSaveArgs.model_validate(args)
                                review.require_answers(tid, [a.model_dump() for a in office_args.answered_questions] if office_args.answered_questions is not None else None, office_args.defer_quote)
                                parsed=OfficeDocument.model_validate(office_args.model_dump(exclude={"review_items", "answered_questions", "defer_quote"}))
                                if link and library.office(link['parent_id']) and not previous_office_read:
                                    raise ValueError('请先用read_previous_office读取上一版结构化成果')
                                if link and not library.office(link['parent_id']) and not previous_read:
                                    raise ValueError('请先读取上一版文字成果')
                                if store.draft(tid): raise ValueError('已有文字分段计划，请完成文字成果或新建办公任务')
                                if library.finish_office(tid,parsed,last_correction,office_args.review_items): return
                                output='用户有新补充或任务状态已变化，请先处理'
                        except ValidationError:
                            output='工具参数不符合结构或大小限制，请检查schema后修正。'
                            call['function']['arguments']='{}'
                        except ValueError as exc:
                            output=str(exc)
                    elif name == "plan_sections":
                        try:
                            parsed = SectionPlanArgs.model_validate(args)
                        except ValidationError:
                            call['function']['arguments'] = '{}'
                            messages.append({'role':'tool','tool_call_id':call['id'],'content':'章节计划参数不符合要求，请检查章节数量、标题和待确认项后重试；尚未保存。'})
                            continue
                        try:
                            review.require_answers(tid, [a.model_dump() for a in parsed.answered_questions] if parsed.answered_questions is not None else None, parsed.defer_quote)
                        except ValueError as exc:
                            call['function']['arguments'] = '{}'
                            messages.append({'role':'tool','tool_call_id':call['id'],'content':str(exc)})
                            continue
                        titles = [title.strip() for title in parsed.titles]
                        if any(not title or len(title) > 100 or "\n" in title for title in titles) or len(set(titles)) != len(titles):
                            output = "章节标题须非空、互不相同且不超过100字"
                        else:
                            output = store.draft_write(tid, 'plan', last_correction, titles=titles, review_items=parsed.review_items) or "章节计划已保存"
                    elif name == "save_section":
                        try:
                            parsed = SectionArgs.model_validate(args)
                        except ValidationError:
                            # The rejected oversized payload is not needed for retry; preserve tool-call pairing without replaying it.
                            call["function"]["arguments"] = "{}"
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "章节参数不符合要求：序号须在计划内，正文须为 1 至 7000 字符。过长参数已省略；请缩短后重新保存该章节，已保存的章节不变。"})
                            continue
                        if link and link["parent_status"] == "completed" and not previous_read:
                            output = "请先读取上一版成果，再决定如何处理"
                        else:
                            outcome = store.draft_write(tid, 'section', last_correction, position=parsed.position, content=parsed.content)
                            output = outcome or "章节已保存"
                            if outcome is None:
                                current_draft = store.draft(tid)
                                if current_draft and all(section["content"] is not None for section in current_draft):
                                    if store.draft_write(tid, 'finish', last_correction) is None:
                                        return
                    elif name == "read_draft":
                        parsed = DraftReadArgs.model_validate(args)
                        saved = store.draft(tid)
                        if not saved or parsed.position > len(saved) or saved[parsed.position-1]["content"] is None:
                            output = "该章节尚未保存"
                        else:
                            output = page_text(saved[parsed.position-1]["content"], parsed.offset, parsed.limit)
                    elif name == "finish_sections":
                        ReadArgs.model_validate(args)
                        outcome = store.draft_write(tid, 'finish', last_correction)
                        if outcome is None:
                            return
                        output = outcome
                    elif name == "read_material":
                        read = ReadArgs.model_validate(args)
                        output = json.dumps(cited_page(task["material"], read.offset, read.limit), ensure_ascii=False)
                        material_read = material_read or bool(json.loads(output)["text"])
                        store.update(tid, "running", "正在读取资料并整理")
                    elif name == "read_task_history":
                        read = ReadArgs.model_validate(args)
                        history_text = json.dumps(store.task_history(tid), ensure_ascii=False)
                        output = page_text(history_text, read.offset, read.limit)
                    elif name == "find_previous_result":
                        find = FindArgs.model_validate(args)
                        previous = store.get(link["parent_id"]) if link else None
                        if not previous:
                            output = "当前任务没有上一版成果；请读取用户资料并按目标继续。"
                        else:
                            text = previous["result"]
                            offsets = []
                            position = 0
                            while len(offsets) < 11:
                                index = text.find(find.keyword, position)
                                if index < 0:
                                    break
                                offsets.append(index)
                                position = index + 1
                            output = json.dumps({"offsets": offsets[:10], "more": len(offsets) > 10}, ensure_ascii=False)
                    elif name == "read_previous_result":
                        read = ReadArgs.model_validate(args)
                        previous = store.get(link["parent_id"]) if link else None
                        if not previous:
                            output = "当前任务没有上一版成果；请读取用户资料并按目标继续。"
                        else:
                            output = page_text(previous["result"], read.offset, read.limit)
                            previous_read = True
                            previous_ranges.append((read.offset, min(read.offset + read.limit, len(previous["result"]))))
                            previous_read_full = read.offset == 0 and len(previous["result"]) <= read.limit
                            store.update(tid, "running", "正在读取上一版成果")
                    elif name == "ask_user":
                        try:
                            parsed = QuestionArgs.model_validate(args)
                        except ValidationError:
                            call['function']['arguments'] = '{}'
                            messages.append({'role':'tool','tool_call_id':call['id'],'content':'追问参数不符合要求：请提供1至3个问题，每个包含问题、推荐和影响；尚未提问。'})
                            continue
                        if not link and task['material'].strip() and not material_read:
                            messages.append({"role": "tool", "tool_call_id": call['id'], "content": "本任务已有粘贴资料，请先用read_material读取再判断缺失信息；不能因附件为空而要求用户重复提供资料。"})
                            continue
                        if not link and not task['material'].strip() and task_sources and not source_read:
                            messages.append({"role": "tool", "tool_call_id": call['id'], "content": "本任务已关联文件资料，请先用read_source读取相关内容，再判断是否需要追问。"})
                            continue
                        if store.wait_for_input(tid, parsed.render(), last_correction, [q.model_dump() for q in parsed.questions] if parsed.questions is not None else None):
                            return
                        if store.get(tid)["status"] == "running":
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "用户已有新的补充，请先处理。"})
                            continue
                        return
                    elif name == "apply_edits":
                        if link and library.office(link['parent_id']):
                            messages.append({"role":"tool","tool_call_id":call['id'],"content":"上一版为办公成果，请读取read_previous_office并用save_office保留结构保存。"})
                            continue
                        if not link or link["parent_status"] != "completed" or not previous_read:
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "请先读取要修改的上一版成果，再使用局部修改。"})
                            continue
                        if store.corrections_since(tid, last_correction):
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "用户有新的补充，请先处理后再保存。"})
                            continue
                        try:
                            parsed_edits = EditsArgs.model_validate(args)
                            original = store.get(link["parent_id"])
                            if not original:
                                raise ValueError("原成果不存在")
                            for edit in parsed_edits.edits:
                                position = original["result"].find(edit.original)
                                if position < 0 or not any(start <= position and position + len(edit.original) <= end for start, end in previous_ranges):
                                    raise ValueError("请先读取包含待修改原文的完整片段")
                            edited = apply_exact_edits(original["result"], parsed_edits.edits)
                        except (ValidationError, ValueError) as exc:
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(exc) if isinstance(exc, ValueError) and not isinstance(exc, ValidationError) else "修改参数不符合要求"})
                            continue
                        if store.finish(tid, edited, last_correction):
                            return
                        if store.get(tid)["status"] == "running":
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "用户有新的补充，请先处理后再保存。"})
                            continue
                        return
                    elif name == "save_artifact":
                        if link and library.office(link['parent_id']):
                            messages.append({"role":"tool","tool_call_id":call['id'],"content":"上一版为办公成果，请用read_previous_office和save_office保留格式。"})
                            continue
                        if store.draft(tid):
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "该任务已有分段计划，请保存全部章节并使用 finish_sections 合并。"})
                            continue
                        if link and not previous_read:
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "请先读取关联的上一版成果，再保存修改。"})
                            continue
                        if link and link["parent_status"] == "completed" and not previous_read_full:
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "未完整读取上一版，不能用全文保存替代原文。请对要修改的内容使用 apply_edits。"})
                            continue
                        if store.corrections_since(tid, last_correction):
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "用户有新的补充，请先处理后再保存。"})
                            continue
                        try:
                            parsed = SaveArgs.model_validate(args)
                        except ValidationError:
                            call['function']['arguments'] = '{}'
                            messages.append({'role':'tool','tool_call_id':call['id'],'content':'草稿参数不符合要求，请检查正文长度和待确认项后重试；尚未保存。'})
                            continue
                        try:
                            review.require_answers(tid, [a.model_dump() for a in parsed.answered_questions] if parsed.answered_questions is not None else None, parsed.defer_quote)
                        except ValueError as exc:
                            call['function']['arguments'] = '{}'
                            messages.append({'role':'tool','tool_call_id':call['id'],'content':str(exc)})
                            continue
                        if store.finish(tid, parsed.content, last_correction, parsed.review_items):
                            return
                        if store.get(tid)["status"] == "running":
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": "用户有新的补充，请先处理后再保存。"})
                            continue
                        return
                    else:
                        raise ValueError("unknown tool")
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
        store.update(tid, "failed", "任务达到执行步数上限，未完成")
    except httpx.TimeoutException:
        store.update(tid, "failed", "模型请求超时，已保存的章节可以继续")
    except httpx.HTTPStatusError as exc:
        store.update(tid, "failed", f"模型接口返回状态 {exc.response.status_code}，已保存的章节可以继续")
    except httpx.HTTPError:
        store.update(tid, "failed", "模型连接失败，已保存的章节可以继续")
    except ValidationError:
        store.update(tid, "failed", "模型输出结构不符合要求，已保存的章节可以继续")
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        store.update(tid, "failed", f"模型或工具参数不符合要求（{type(exc).__name__}），已保存的章节可以继续")
    except Exception:
        store.update(tid, "failed", "任务处理失败，已保存的章节可以继续")
