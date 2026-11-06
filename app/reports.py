import json
import math
from typing import Literal
from pydantic import Field
from .domain import StrictModel,uid
from .database import transaction,now,connect,rows
from .adapter import erp


ChartType=Literal['table','bar','line','area','pie','scatter','heatmap','pivot']


class ReportSpec(StrictModel):
    title: str=Field(min_length=1,max_length=160)
    chart_type: ChartType='table'
    sql: str=Field(default='',max_length=12000)
    rows: list[dict]=Field(default_factory=list,max_length=500)
    x: str=''
    y: list[str]=Field(default_factory=list,max_length=8)
    group: str=''
    description: str=Field(default='',max_length=2000)


async def create_report(spec:ReportSpec):
    if spec.sql:
        data=await erp.query(spec.sql)
    else:
        columns=list(spec.rows[0]) if spec.rows else []
        if any(set(row)!=set(columns) for row in spec.rows):
            raise ValueError('每行必须使用相同列名')
        data={'columns':columns,'rows':spec.rows,'as_of':now(),'source':'手工编辑数据','truncated':False}
    if len(data['columns'])>50:
        raise ValueError('报表最多支持50列')
    for row in data['rows']:
        for value in row.values():
            if not isinstance(value,(str,int,float,bool,type(None))) or (isinstance(value,float) and not math.isfinite(value)):
                raise ValueError('单元格只接受有限数字、文本、布尔值或空值')
    if spec.chart_type not in ('table',):
        if not spec.x or not spec.y or spec.x not in data['columns'] or any(y not in data['columns'] for y in spec.y):
            raise ValueError('请选择有效的维度列X与数值列Y')
        for row in data['rows']:
            if any(not isinstance(row[y],(int,float)) or isinstance(row[y],bool) for y in spec.y):
                raise ValueError('数值列Y必须全部是数字，请使用COALESCE处理空值')
        if spec.chart_type=='scatter' and any(not isinstance(row[spec.x],(int,float)) for row in data['rows']):
            raise ValueError('散点图X轴必须为数值')
        if spec.chart_type in ('pivot','heatmap') and spec.group not in data['columns']:
            raise ValueError('透视表和热力图需要有效的分组列')
    identity=uid('RPT')
    body=spec.model_dump(exclude={'rows','sql'})
    stamp=now()
    with transaction('agent') as db:
        db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?)',(identity,spec.title,spec.chart_type,json.dumps(body,ensure_ascii=False),json.dumps(data,ensure_ascii=False),spec.sql,stamp))
    return {'id':identity,**body,'data':data,'sql':spec.sql,'created_at':stamp}


def list_reports():
    db=connect('agent')
    try:
        return rows(db,'SELECT id,title,chart_type,created_at FROM reports ORDER BY created_at DESC LIMIT 100')
    finally:
        db.close()


def get_report(identity):
    db=connect('agent')
    try:
        row=db.execute('SELECT * FROM reports WHERE id=?',(identity,)).fetchone()
        if not row:
            raise ValueError('报表不存在')
        return {'id':row['id'],**json.loads(row['spec']),'data':json.loads(row['data']),'sql':row['sql'],'created_at':row['created_at']}
    finally:
        db.close()
