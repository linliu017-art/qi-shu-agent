from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from . import store, library
from .office import OfficeDocument, export_office
from .word_export import export_docx
from .guides import GUIDES
import re

router=APIRouter(prefix='/api/v1')


@router.post('/materials',status_code=201)
async def upload_material(file: UploadFile=File(...), parent_id: str | None=Form(None)):
    try:
        raw=await file.read(library.MAX_BYTES+1)
        if len(raw)>library.MAX_BYTES: raise HTTPException(413,'文件超过10MB')
        try:
            return library.upload(file.filename or '',raw,parent_id)
        except LookupError:
            raise HTTPException(404,'父资料版本不存在') from None
        except Exception as exc:
            # Parsers may embed file contents in their exceptions; never echo them.
            message=str(exc) if type(exc) is ValueError else '文件内容无效或格式不受支持'
            raise HTTPException(400,message) from None
    finally:
        await file.close()


@router.get('/materials')
def materials(offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    return {'materials':library.list_materials(offset,limit),'offset':offset,'limit':limit}


def material_or_404(sid):
    row=library.get(sid)
    if not row: raise HTTPException(404,'资料不存在')
    return row


@router.get('/materials/{sid}')
def material_preview(sid:str,offset:int=Query(0,ge=0),limit:int=Query(3000,ge=1,le=10000)):
    row=material_or_404(sid)
    if offset>len(row['text']): raise HTTPException(400,'读取位置超出内容')
    end=min(offset+limit,len(row['text']))
    return {**library.metadata(row),'text':row['text'][offset:end],'offset':offset,'next_offset':end if end<len(row['text']) else None,'total_characters':len(row['text'])}


@router.get('/materials/{sid}/download')
def download_material(sid:str):
    row=material_or_404(sid)
    return Response(row['content'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="source.{row["kind"]}"','Cache-Control':'no-store'})


class TextEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content:str=Field(min_length=1,max_length=100000)
    expected_version_id:str=Field(min_length=1,max_length=64)


class OfficeEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version_id:str=Field(min_length=1,max_length=64)
    document:OfficeDocument


def task_or_404(tid):
    task=store.get(tid)
    if not task: raise HTTPException(404,'任务不存在')
    return task


@router.post('/tasks/{tid}/edit',status_code=201)
def edit_text(tid:str,data:TextEdit):
    task_or_404(tid)
    if not data.content.strip(): raise HTTPException(400,'成果不能为空')
    try: return library.edit(tid,data.expected_version_id,content=data.content)
    except ValueError as exc: raise HTTPException(409,str(exc)) from None


@router.get('/tasks/{tid}/office')
def office_content(tid:str):
    task_or_404(tid)
    result=library.office(tid)
    if not result: raise HTTPException(404,'该任务没有结构化办公成果')
    return {'task_id':tid,'document':result,'sources':library.sources(tid)}


@router.post('/tasks/{tid}/office/edit',status_code=201)
def edit_office(tid:str,data:OfficeEdit):
    task_or_404(tid)
    try: return library.edit(tid,data.expected_version_id,document=data.document)
    except ValueError as exc: raise HTTPException(409,str(exc)) from None


@router.get('/artifacts')
def artifact_list(offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    with store.connection() as db:
        rows=db.execute("SELECT id,goal,result,created_at FROM tasks WHERE owner_id='local-user' AND status='completed' ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset)).fetchall()
    results=[]
    for row in rows:
        office=library.office(row['id'])
        heading = re.search(r'^#\s+(.+)$', row['result'], re.MULTILINE)
        title = office['title'] if office else heading.group(1).strip() if heading else store.original_goal(row['id'])
        results.append({'task_id':row['id'],'title':title,'kind':office['kind'] if office else 'markdown','created_at':row['created_at'],'sources':library.sources(row['id'])})
    return {'artifacts':results,'offset':offset,'limit':limit}


@router.get('/tasks/{tid}/export/{format}')
def export_artifact(tid:str,format:str):
    task=task_or_404(tid)
    if task['status']!='completed': raise HTTPException(409,'仅支持已完成成果')
    office=library.office(tid)
    if format=='md': data=task['result'].encode();mime='text/markdown; charset=utf-8'
    elif format=='docx': data=export_docx(task['result']);mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif format in ('xlsx','pptx'):
        if not office or office['kind']!=format: raise HTTPException(409,'成果格式不匹配，请先让Agent生成对应格式')
        data=export_office(OfficeDocument.model_validate(office))
        mime={'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}[format]
    else: raise HTTPException(400,'不支持的导出格式')
    return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="result.{format}"','Cache-Control':'no-store'})


@router.get('/business-guides')
def business_guides():
    return {'guides':[{'id':k, **{field:v[field] for field in ('title','version','source_skill','supported_mode','references') if field in v}} for k,v in GUIDES.items()]}
