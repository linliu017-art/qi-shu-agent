from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from . import agent, store, library, review
from typing import Literal

pool = ThreadPoolExecutor(max_workers=2)

@asynccontextmanager
async def lifespan(app):
    store.init()
    yield

app = FastAPI(lifespan=lifespan)

class CorrectionInput(BaseModel):
    content: str = Field(min_length=1, max_length=10000)

class TaskInput(BaseModel):
    goal: str = Field(min_length=1, max_length=10000)
    material: str = Field(default="", max_length=100000)
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": {404: "NOT_FOUND", 409: "CONFLICT"}.get(exc.status_code, "BAD_REQUEST"), "message": str(exc.detail)}})

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"code": "INVALID_INPUT", "message": "输入格式或长度不符合要求"}})

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "服务处理失败"}})

@app.get("/api/v1/health")
def health():
    return {"status": "ok"}

@app.post("/api/v1/tasks", status_code=201)
def create_task(data: TaskInput):
    if not data.goal.strip():
        raise HTTPException(400, "请输入任务目标")
    try:
        task, created = store.create_once(data.goal, data.material, data.source_ids, data.client_request_id)
    except store.RequestConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from None
    if created:
        try:
            pool.submit(agent.run, task["id"])
        except RuntimeError:
            store.update(task["id"], 'failed', '任务已保存，但执行服务不可用；请稍后新建任务')
            task = store.get(task["id"])
    return task

@app.get("/api/v1/tasks")
def list_tasks():
    return {"tasks": store.list_tasks()}

@app.get("/api/v1/task-threads")
def list_task_threads():
    return {"tasks": store.list_task_threads()}

@app.get("/api/v1/tasks/{tid}")
def get_task(tid: str):
    task = store.get(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    task["original_goal"] = store.original_goal(tid)
    task["review"] = review.get(tid)
    task["sources"] = library.sources(tid)
    office = library.office(tid)
    task["artifact_kind"] = office['kind'] if office else 'markdown'
    task["draft"] = store.draft(tid)
    task["usage"] = store.task_usage(tid)
    task["cache_usage"] = store.task_cache_usage(tid)
    return task

@app.post("/api/v1/tasks/{tid}/cancel")
def cancel_task(tid: str):
    if not store.get(tid):
        raise HTTPException(404, "任务不存在")
    if not store.cancel(tid):
        raise HTTPException(409, "该任务已结束，不能停止")
    return store.get(tid)

@app.post("/api/v1/tasks/{tid}/corrections", status_code=201)
def correct_task(tid: str, data: CorrectionInput):
    task = store.get(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    content = data.content.strip()
    if not content:
        raise HTTPException(400, "请输入补充要求")
    if task["status"] in ("queued", "running"):
        if not store.add_correction(tid, content):
            raise HTTPException(409, "任务状态已变化，请重试")
        return {"status": "queued", "message": "已保存补充要求，将在下一步处理"}
    if task["status"] in ("completed", "waiting"):
        new_task = store.create_followup(tid, content)
        if not new_task:
            raise HTTPException(409, "任务状态已变化，请重试")
        new_task["original_goal"] = store.original_goal(new_task["id"])
        pool.submit(agent.run, new_task["id"])
        return {"status": "new_task", "task": new_task}
    raise HTTPException(409, "该任务没有可继续修改的成果")

@app.post("/api/v1/tasks/{tid}/resume")
def resume_task(tid: str):
    if not store.get(tid):
        raise HTTPException(404, "任务不存在")
    if not store.resume(tid):
        raise HTTPException(409, "该任务没有可继续的分段草稿")
    pool.submit(agent.run, tid)
    return store.get(tid)

class RestoreInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)


def completed_task(tid):
    task = store.get(tid)
    if not task:
        raise HTTPException(404, '任务不存在')
    if task['status'] != 'completed':
        raise HTTPException(409, '仅已完成成果支持此操作')
    return task


@app.get('/api/v1/tasks/{tid}/versions')
def task_versions(tid: str):
    if not store.get(tid):
        raise HTTPException(404, '任务不存在')
    return {'versions': store.versions(tid)}


@app.get('/api/v1/tasks/{tid}/diff')
def task_diff(tid: str, base_id: str):
    from difflib import SequenceMatcher
    task = completed_task(tid)
    if base_id not in {v['id'] for v in store.versions(tid)}:
        raise HTTPException(409, '只能比较同一成果的已完成版本')
    before = completed_task(base_id)['result'].splitlines()
    after = task['result'].splitlines()
    changes = []
    for op,i,j,k,l in SequenceMatcher(None,before,after).get_opcodes():
        if op == 'equal':
            changes.append({'kind':'equal','lines':after[k:l]})
        else:
            if i != j:
                changes.append({'kind':'delete','lines':before[i:j]})
            if k != l:
                changes.append({'kind':'insert','lines':after[k:l]})
    return {'base_id':base_id, 'target_id':tid, 'changes':changes}


@app.post('/api/v1/tasks/{tid}/restore', status_code=201)
def restore_version(tid: str, data: RestoreInput):
    completed_task(tid)
    restored = store.restore(tid, data.source_id)
    if not restored:
        raise HTTPException(409, '只能恢复同一成果的已完成版本')
    return restored


@app.get('/api/v1/tasks/{tid}/export.docx')
def export_word(tid: str):
    from fastapi.responses import Response
    from .word_export import export_docx
    task = completed_task(tid)
    return Response(export_docx(task['result']), media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition':'attachment; filename="result.docx"','Cache-Control':'no-store'})

from .library_api import router as library_router
app.include_router(library_router)


class ConfirmReviewInput(BaseModel):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_all: Literal[True]


@app.post('/api/v1/tasks/{tid}/review/confirm')
def confirm_review(tid: str, data: ConfirmReviewInput):
    try:
        return review.confirm(tid, data.expected_revision)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
