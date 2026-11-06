from .permissions import command_schema
import hmac
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from .config import INTERNAL_TOKEN
from .database import init_erp
from . import domain
from .auth import resolve_session

def actor_session(x_actor_session: str = Header(default="")):
    return resolve_session(x_actor_session)


@asynccontextmanager
async def lifespan(app):
    if not INTERNAL_TOKEN:
        raise RuntimeError('请通过启动器启动，内部服务令牌不能为空')
    init_erp()
    yield


def authenticate(x_internal_token: str = Header(default='')):
    if not INTERNAL_TOKEN or not hmac.compare_digest(x_internal_token,INTERNAL_TOKEN):
        raise HTTPException(401,'内部服务认证失败')


app=FastAPI(title='织序 ERP + MES 内部业务服务',lifespan=lifespan,dependencies=[Depends(authenticate)],docs_url=None,redoc_url=None,openapi_url=None)


@app.exception_handler(domain.BusinessError)
async def business_error(request,exc):
    return JSONResponse(status_code=409,content={'detail':str(exc)})


@app.exception_handler(ValidationError)
async def validation_error(request,exc):
    return JSONResponse(status_code=422,content={'detail':str(exc)})


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request,exc):
    return JSONResponse(status_code=409,content={'detail':'数据约束冲突，操作已回滚'})


class Command(BaseModel):
    params: dict
    request_id: str = Field(min_length=8,max_length=160)


class Query(BaseModel):
    sql: str = Field(min_length=1,max_length=12000)


class Workflow(BaseModel):
    steps: list[dict] = Field(min_length=1,max_length=12)
    inputs: dict
    request_id: str = Field(min_length=8,max_length=160)


@app.get('/health')
def health():
    return {'status':'ok','service':'erp-mes'}


@app.get('/catalog')
def catalog(actor=Depends(actor_session)):
    return domain.catalog(actor)


@app.get('/commands')
def commands(actor=Depends(actor_session)):
    return {name:{'description':desc,'schema':command_schema(actor,name,model)} for name,(model,desc) in domain.COMMANDS.items() if name in actor['policy']['commands']}


@app.post('/query')
def query(body: Query,actor=Depends(actor_session)):
    return domain.query(body.sql,actor)


@app.post('/commands/{operation}')
def command(operation:str,body:Command,actor=Depends(actor_session)):
    return domain.execute(operation,body.params,body.request_id,actor)


@app.post('/workflow')
def workflow(body:Workflow,actor=Depends(actor_session)):
    return domain.execute_workflow(body.steps,body.inputs,body.request_id,actor)
