"""Local native-editor integration, disabled until explicitly configured.

This module is experimental. Do not enable it before testing a real editor and
complex documents. JWT secrets and file contents are never logged.
"""
import os
from typing import Literal
from urllib.parse import urlsplit
import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from . import library,office_sessions
from .office_security import validate_editor_download,verify_editor_token

router=APIRouter(prefix='/api/v1/office-editor')


def _local_origin(value):
    try:
        u=urlsplit(value);_ = u.port
    except ValueError:
        raise ValueError('编辑服务地址配置无效') from None
    if (u.scheme not in ('http','https') or u.hostname not in ('127.0.0.1','localhost','::1')
        or u.username is not None or u.password is not None or u.path not in ('','/') or u.query or u.fragment):
        raise ValueError('编辑服务仅支持配置本机地址')
    return value.rstrip('/')


def settings():
    if os.getenv('OFFICE_EDITOR_ENABLED')!='1':raise HTTPException(503,'复杂 Office 编辑器尚未启用')
    secret=os.getenv('OFFICE_EDITOR_SECRET','')
    if len(secret)<32:raise HTTPException(503,'复杂 Office 编辑器尚未完成安全配置')
    try:
        editor=_local_origin(os.getenv('OFFICE_EDITOR_ORIGIN',''))
        storage=_local_origin(os.getenv('OFFICE_STORAGE_ORIGIN',''))
    except ValueError as exc:raise HTTPException(503,str(exc)) from None
    return editor,storage,secret


@router.get('/capability')
def capability():
    try:settings()
    except HTTPException:return {'enabled':False}
    return {'enabled':True}


@router.post('/import',status_code=201)
async def import_original(file:UploadFile=File(...)):
    settings()
    try:
        raw=await file.read(library.MAX_BYTES+1)
        if len(raw)>library.MAX_BYTES:raise HTTPException(413,'文件超过10MB')
        try:return library.import_native_office(file.filename or '',raw)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        except Exception:raise HTTPException(400,'文件内容无效或格式不受支持') from None
    finally:await file.close()


class StartInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task_id:str=Field(min_length=1,max_length=64,pattern=r'^[a-f0-9]+$')
    mode:Literal['edit','view']='edit'


@router.post('/sessions',status_code=201)
def start_session(data:StartInput):
    editor,storage,secret=settings()
    try:session=office_sessions.create(data.task_id)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    sid=session['id'];kind=session['kind']
    config={'document':{'fileType':kind,'key':sid,'title':'成果.'+kind,
                        'url':f'{storage}/api/v1/office-editor/sessions/{sid}/file',
                        'permissions':{'edit':data.mode=='edit','download':True}},
            'documentType':{'docx':'word','xlsx':'cell','pptx':'slide'}[kind],
            'editorConfig':{'mode':data.mode,'lang':'zh-CN','callbackUrl':f'{storage}/api/v1/office-editor/sessions/{sid}/callback',
                            'user':{'id':'local-user','name':'本机用户'},'customization':{'autosave':True,'forcesave':False}}}
    config['token']=jwt.encode(config,secret,algorithm='HS256')
    return {'session_id':sid,'editor_origin':editor,'config':config}


@router.get('/sessions/{sid}/file')
def session_file(sid:str,request:Request):
    _,storage,secret=settings();session=office_sessions.get(sid)
    if not session or session['status']!='open':raise HTTPException(404,'编辑会话不存在或已结束')
    expected=f'{storage}/api/v1/office-editor/sessions/{sid}/file'
    try:verify_editor_token(request.headers.get('Authorization',''),secret,{'url':expected})
    except ValueError:raise HTTPException(403,'编辑服务认证失败') from None
    return Response(session['snapshot'],media_type='application/octet-stream',headers={'Cache-Control':'no-store'})


def _download(url,origin):
    validate_editor_download(url,origin)
    data=bytearray()
    with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
        with client.stream('GET',url) as response:
            if response.status_code!=200:raise ValueError('无法读取编辑后的文件')
            for part in response.iter_bytes():
                data.extend(part)
                if len(data)>library.MAX_BYTES:raise ValueError('编辑后的文件超过10MB')
    if not data:raise ValueError('编辑后的文件为空')
    return bytes(data)


@router.post('/sessions/{sid}/callback')
async def callback(sid:str,request:Request):
    try:
        editor,_,secret=settings();session=office_sessions.get(sid)
        if not session:return {'error':1}
        raw=await request.body()
        if len(raw)>100000:return {'error':1}
        import json
        body=json.loads(raw)
        if not isinstance(body,dict) or body.get('key')!=sid or type(body.get('status')) is not int:return {'error':1}
        status=body['status'];expected={'key':sid,'status':status}
        if status in (2,6):
            if not isinstance(body.get('url'),str):return {'error':1}
            expected['url']=body['url']
        verify_editor_token(request.headers.get('Authorization',''),secret,expected)
        if status==1:return {'error':0}
        if status==4:
            result=office_sessions.finish(sid,session['snapshot'])
            return {'error':0 if result['status'] in ('unchanged','saved') else 1}
        if status==2:
            saved=_download(body['url'],editor)
            try:result=office_sessions.finish(sid,saved)
            except (ValueError,TypeError):
                # Preserve the candidate for the user even if parsing fails;
                # acknowledging receipt is not the same as creating a version.
                return {'error':0 if office_sessions.retain_failed(sid,saved) else 1}
            return {'error':0 if result['status'] in ('saved','unchanged','review_required') else 1}
        # Forcesave and errors are intentionally not acknowledged as saved.
        return {'error':1}
    except (ValueError,httpx.HTTPError,HTTPException,TypeError):
        return {'error':1}


@router.get('/sessions/{sid}')
def session_status(sid:str):
    settings();session=office_sessions.get(sid)
    if not session:raise HTTPException(404,'编辑会话不存在')
    import json
    warnings=json.loads(session['review_details']) if session['review_details'] else []
    return {'id':sid,'status':session['status'],'task_id':session['result_id'],'can_recover':session['recovery'] is not None,'warnings':warnings}


@router.post('/sessions/{sid}/approve')
def approve_session(sid:str):
    settings()
    try:return office_sessions.approve(sid)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None


@router.get('/sessions/{sid}/recovery')
def session_recovery(sid:str):
    settings();session=office_sessions.get(sid)
    if not session or session['recovery'] is None:raise HTTPException(404,'没有可恢复的编辑结果')
    return Response(session['recovery'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="recovery.{session["kind"]}"','Cache-Control':'no-store'})
