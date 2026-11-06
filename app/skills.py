from .auth import current_actor, require_admin
import json
import re
from typing import Literal
from pydantic import Field, model_validator
from .domain import StrictModel, COMMANDS
from .database import connect, transaction
from .config import ROOT


class SkillInput(StrictModel):
    type: Literal['string','number','integer','boolean'] = 'string'
    description: str = Field(default='',max_length=300)
    required: bool = True
    default: str | float | bool | None = None


class SkillStep(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,40}$')
    operation: str
    params: dict


class Skill(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{1,60}$')
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(min_length=1,max_length=800)
    version: str = '1.0.0'
    enabled: bool = True
    instructions: str = Field(min_length=1,max_length=8000)
    inputs: dict[str,SkillInput] = Field(default_factory=dict,max_length=20)
    required_tables: list[str] = Field(default_factory=list,max_length=20)
    steps: list[SkillStep] = Field(default_factory=list,max_length=12)

    @model_validator(mode='after')
    def check_steps(self):
        seen=set()
        for step in self.steps:
            if step.id in seen or step.operation not in COMMANDS:
                raise ValueError('步骤ID重复或业务操作未注册')
            model=COMMANDS[step.operation][0]
            if set(step.params)-set(model.model_fields):
                raise ValueError('流程包含未知业务参数')
            def check(value):
                if isinstance(value,dict):
                    for v in value.values(): check(v)
                elif isinstance(value,list):
                    for v in value: check(v)
                elif isinstance(value,str) and value.startswith('$'):
                    parts=value[1:].split('.')
                    if len(parts)<2 or parts[0] not in ('input','steps'):
                        raise ValueError('流程引用格式错误')
                    if parts[0]=='input' and parts[1] not in self.inputs:
                        raise ValueError('引用了未声明的输入')
                    if parts[0]=='steps' and parts[1] not in seen:
                        raise ValueError('步骤只能引用此前已完成的步骤')
            check(step.params)
            for name,field in model.model_fields.items():
                if field.is_required() and name not in step.params:
                    raise ValueError(f'步骤缺少必要参数：{name}')
            seen.add(step.id)
        return self


def list_skills(unfiltered=False):
    found={}
    for path in sorted((ROOT/'skills').glob('*.json')):
        body=Skill.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
        found[body['id']]=body
    db=connect('agent')
    try:
        for row in db.execute('SELECT body FROM skill_config'):
            body=Skill.model_validate_json(row['body']).model_dump()
            found[body['id']]=body
    finally:
        db.close()
    if unfiltered: return list(found.values())
    actor=current_actor()
    def allowed(skill):
        if actor['role_id']=='admin': return True
        required=skill['required_tables']
        return skill['enabled'] and bool(required or skill['steps']) and set(required)<=set(actor['policy']['tables']) and all(s['operation'] in actor['policy']['commands'] for s in skill['steps'])
    return [skill for skill in found.values() if allowed(skill)]


def save_skill(body):
    require_admin()
    value=Skill.model_validate(body).model_dump()
    with transaction('agent') as db:
        db.execute('INSERT INTO skill_config VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(value['id'],json.dumps(value,ensure_ascii=False)))
    return value


def get_skill(identity):
    for skill in list_skills():
        if skill['id']==identity:
            if not skill['enabled']:
                raise ValueError('此技能已禁用')
            return skill
    raise ValueError('技能不存在')


def validate_inputs(skill,inputs):
    if set(inputs)-set(skill['inputs']):
        raise ValueError('包含未定义的技能输入')
    result={}
    for key,spec in skill['inputs'].items():
        value=inputs.get(key,spec.get('default'))
        if value is None:
            if spec['required']:
                raise ValueError(f'缺少技能输入：{key}')
            continue
        types={'string':str,'number':(int,float),'integer':int,'boolean':bool}
        if not isinstance(value,types[spec['type']]) or (spec['type'] in ('number','integer') and isinstance(value,bool)):
            raise ValueError(f'技能输入类型不匹配：{key}')
        result[key]=value
    return result
