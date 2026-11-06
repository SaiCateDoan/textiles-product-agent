from .permissions import command_schema
import asyncio
import csv
import io
import json
import os
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,Field
from .config import ROOT,APP_PORT,MODEL
from .database import init_agent,connect,transaction,now,rows
from .domain import uid,COMMANDS
from .adapter import erp,AdapterError
from .runtime import run_agent
from .skills import list_skills,save_skill,Skill
from .reports import ReportSpec,create_report,list_reports,get_report

from . import auth
from .permissions import require_command

tasks=set()


@asynccontextmanager
async def lifespan(app):
    init_agent()
    yield
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks,return_exceptions=True)


app=FastAPI(title='织序 · 工厂智能工作台',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])


@app.middleware('http')
async def local_protection(request:Request,call_next):
    if request.url.path.startswith('/api/'):
        origin=request.headers.get('origin')
        if origin and origin not in (f'http://127.0.0.1:{APP_PORT}',f'http://localhost:{APP_PORT}'):
            return JSONResponse(status_code=403,content={'detail':'仅允许同源访问'})
        public=request.url.path in ('/api/health','/api/auth/login')
        context=None
        try:
            if not public:
                actor=auth.resolve_session(auth.token_digest(request.cookies.get(auth.COOKIE,'')))
                context=auth.session_context.set(actor['session_hash'])
                # These headers bind an already-open page to its account; they never establish identity.
                for header,key in [('x-demo-user','id'),('x-demo-access','access_tag')]:
                    expected=request.headers.get(header)
                    if expected and expected!=actor[key]:
                        raise HTTPException(401,'账号或权限已切换，请重新登录')
                if request.method not in ('GET','HEAD','OPTIONS') and not hmac.compare_digest(request.headers.get('x-demo-token',''),actor['csrf']):
                    raise HTTPException(403,'页面会话已失效，请重新登录')
            elif request.url.path=='/api/auth/login' and request.headers.get('x-demo-login')!='1':
                raise HTTPException(403,'请从登录页面登录')
            response=await call_next(request)
        except HTTPException as exc:
            response=JSONResponse(status_code=exc.status_code,content={'detail':exc.detail})
        finally:
            if context is not None: auth.session_context.reset(context)
    else:
        response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(AdapterError)
@app.exception_handler(ValueError)
async def value_error(request,exc):
    return JSONResponse(status_code=400,content={'detail':str(exc)})



class LoginBody(BaseModel):
    username: str=Field(min_length=1,max_length=80)
    password: str=Field(min_length=1,max_length=128)


@app.post('/api/auth/login')
def login(body:LoginBody,request:Request,response:Response):
    token=auth.login(body.username,body.password,request.client.host if request.client else 'local')
    response.set_cookie(auth.COOKIE,token,max_age=auth.TTL,httponly=True,samesite='strict',path='/')
    return {'status':'ok'}


@app.post('/api/auth/logout')
def logout(response:Response):
    actor=auth.current_actor()
    with transaction('agent') as db:
        db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(actor['session_hash'],))
    response.delete_cookie(auth.COOKIE,path='/')
    return {'status':'ok'}


@app.get('/api/admin')
def admin_data():
    return auth.admin_data()


@app.put('/api/admin/users/{identity}')
def save_user(identity:str,body:dict):
    return auth.save_user(identity,body)


@app.put('/api/admin/roles/{identity}')
def save_role(identity:str,body:dict):
    return auth.save_role(identity,body)


@app.get('/api/bootstrap')
async def bootstrap():
    status='ok'
    try:
        await erp.request('GET','/health')
    except AdapterError:
        status='unavailable'
    actor=auth.current_actor()
    return {'user':auth.public_actor(actor),'access_tag':actor['access_tag'],'token':actor['csrf'],'model':MODEL,'key_configured':bool(os.getenv('DEEPSEEK_API_KEY')),'erp_status':status,'now':now(),'commands':{k:{'description':v[1],'schema':command_schema(actor,k,v[0])} for k,v in COMMANDS.items() if k in actor['policy']['commands']}}


@app.get('/api/health')
async def health():
    return {'status':'ok','service':'textiles-agent','model':MODEL,'instance_id':os.getenv('DEMO_LAUNCH_ID'),'erp':await erp.request('GET','/health')}


@app.get('/api/catalog')
async def catalog():
    return await erp.catalog()


class QueryBody(BaseModel):
    sql: str=Field(min_length=1,max_length=12000)


@app.post('/api/query')
async def query(body:QueryBody):
    return await erp.query(body.sql)


class CommandBody(BaseModel):
    params: dict
    request_id: str=Field(min_length=8,max_length=160)


@app.post('/api/business/{operation}')
async def business(operation:str,body:CommandBody):
    require_command(auth.current_actor(),operation)
    if operation not in COMMANDS:
        raise HTTPException(404,'未注册业务操作')
    params=COMMANDS[operation][0].model_validate(body.params).model_dump(mode='json',exclude_none=True)
    return await erp.command(operation,params,body.request_id)


@app.get('/api/dashboard')
async def dashboard():
    actor=auth.current_actor()
    tables=actor['policy']['tables']
    cards=[]
    candidates=[('orders',['quantity','unit_price'],'订单总金额','元','ROUND(COALESCE(SUM(quantity*unit_price),0),2)'),
                ('orders',['status'],'待交付订单','单',"SUM(CASE WHEN status!='shipped' THEN 1 ELSE 0 END)"),
                ('work_orders',['status'],'生产中工单','张',"SUM(CASE WHEN status='running' THEN 1 ELSE 0 END)"),
                ('materials',['stock','safety_stock'],'低库存原料','种','SUM(CASE WHEN stock<safety_stock THEN 1 ELSE 0 END)'),
                ('production_reports',['good_qty','bad_qty'],'综合良品率','%','ROUND(100.0*SUM(good_qty)/NULLIF(SUM(good_qty+bad_qty),0),2)'),
                ('purchases',['status'],'待收货采购单','张',"SUM(CASE WHEN status='ordered' THEN 1 ELSE 0 END)")]
    for table,columns,label,unit,expr in candidates:
        if set(columns)<=set(tables.get(table,[])):
            result=await erp.query(f'SELECT {expr} value FROM {table}')
            cards.append({'label':label,'unit':unit,'value':result['rows'][0]['value'] or 0})
    sections=[]
    for table in ['orders','work_orders','materials','purchases','products']:
        if table in tables:
            result=await erp.query(f'SELECT * FROM {table} LIMIT 8')
            sections.append({'table':table,'data':result})
    return {'cards':cards,'sections':sections,'as_of':now()}



class ChatBody(BaseModel):
    message: str=Field(min_length=1,max_length=16000)
    session_id: str | None=None


@app.post('/api/chat',status_code=202)
async def chat(body:ChatBody):
    if not body.message.strip():
        raise HTTPException(422,'消息不能为空')
    session_id=body.session_id or uid('CHAT')
    run_id=uid('RUN')
    with transaction('agent') as db:
        if body.session_id: auth.ensure_session(db,session_id)
        existing=db.execute('SELECT id FROM sessions WHERE id=?',(session_id,)).fetchone()
        if body.session_id and not existing:
            raise HTTPException(404,'会话不存在')
        if db.execute("SELECT 1 FROM runs WHERE session_id=? AND status='running'",(session_id,)).fetchone():
            raise HTTPException(409,'该会话仍有任务执行中')
        if not existing:
            db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',(session_id,body.message[:45],now(),*auth.artifact_owner()))
        db.execute('INSERT INTO runs(id,session_id,status,created_at) VALUES(?,?,?,?)',(run_id,session_id,'running',now()))
        db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(session_id,'user',json.dumps({'role':'user','content':body.message},ensure_ascii=False),now()))
    task=asyncio.create_task(run_agent(run_id,session_id))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return {'session_id':session_id,'run_id':run_id}


@app.get('/api/sessions')
def sessions():
    db=connect('agent')
    try:
        return rows(db,'SELECT id,title,created_at FROM sessions WHERE owner_id=? AND access_tag=? ORDER BY created_at DESC LIMIT 100',auth.artifact_owner())
    finally:
        db.close()


@app.get('/api/sessions/{identity}')
def session(identity:str):
    db=connect('agent')
    try:
        auth.ensure_session(db,identity)
        messages=rows(db,'SELECT * FROM messages WHERE session_id=? ORDER BY id',(identity,))
        for message in messages:
            message['body']=json.loads(message.pop('content'))
        return {'messages':messages,'runs':rows(db,'SELECT * FROM runs WHERE session_id=? ORDER BY created_at',(identity,))}
    finally:
        db.close()


@app.get('/api/runs/{identity}')
def run(identity:str,after:int=0):
    db=connect('agent')
    try:
        row=db.execute('SELECT * FROM runs WHERE id=?',(identity,)).fetchone()
        if not row:
            raise HTTPException(404,'任务不存在')
        auth.ensure_session(db,row['session_id'])
        result=dict(row)
        result['usage']=json.loads(result['usage'])
        result['events']=rows(db,'SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id',(identity,after))
        for e in result['events']:
            e['payload']=json.loads(e['payload'])
        return result
    finally:
        db.close()


@app.get('/api/skills')
def skills():
    return list_skills()


@app.put('/api/skills/{identity}')
def update_skill(identity:str,body:Skill):
    auth.require_admin()
    if body.id!=identity:
        raise HTTPException(400,'技能ID不匹配')
    return save_skill(body.model_dump())


@app.get('/api/reports')
def reports():
    return list_reports()


@app.post('/api/reports',status_code=201)
async def report_create(body:ReportSpec):
    return await create_report(body)


@app.get('/api/reports/{identity}')
def report_detail(identity:str):
    return get_report(identity)


@app.get('/api/reports/{identity}/csv')
def report_csv(identity:str):
    report=get_report(identity)
    output=io.StringIO()
    writer=csv.writer(output)
    def safe(value):
        return "'"+value if isinstance(value,str) and value.startswith(('=','+','-','@','\t','\r')) else value
    writer.writerow([safe(c) for c in report['data']['columns']])
    for row in report['data']['rows']:
        writer.writerow([safe(row[c]) for c in report['data']['columns']])
    return Response(content='\ufeff'+output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{identity}.csv"'})


@app.post('/api/shutdown')
async def shutdown():
    auth.require_admin()
    path=os.getenv('DEMO_SHUTDOWN_FILE')
    if not path:
        raise HTTPException(409,'请使用一键启动器启动，才能关闭整个Demo')
    if tasks:
        raise HTTPException(409,'Agent仍在执行任务，请等待完成后关闭，避免业务执行中断')
    Path(path).write_text('shutdown',encoding='utf-8')
    return {'status':'stopping','message':'正在关闭整个Demo，数据已保存。'}


@app.get('/')
def index():
    return FileResponse(ROOT/'frontend'/'index.html')


app.mount('/static',StaticFiles(directory=ROOT/'frontend'),name='static')
