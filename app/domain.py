"""ERP/MES invariants live here, never in model prompts or the adapter."""
import hashlib
import json
import sqlite3
import uuid
from datetime import date
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from .database import now, rows, transaction, connect


class BusinessError(ValueError):
    pass


Positive = Annotated[float, Field(gt=0, le=1e7, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, le=1e7, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CreateOrder(StrictModel):
    customer_id: str
    product_id: str
    quantity: Positive
    due_date: date
    unit_price: Positive | None = None


class PlanOrder(StrictModel):
    order_id: str
    machine_id: str
    quantity: Positive | None = None


class ReleaseWorkOrder(StrictModel):
    work_order_id: str


class ReportProduction(StrictModel):
    work_order_id: str
    good_qty: Nonnegative
    bad_qty: Nonnegative = 0
    defect: str = Field(default='', max_length=300)


class CreatePurchase(StrictModel):
    material_id: str
    quantity: Positive


class ReceivePurchase(StrictModel):
    purchase_id: str


class ShipOrder(StrictModel):
    order_id: str
    quantity: Positive


COMMANDS = {
    'create_order': (CreateOrder, '创建销售订单，数量单位为米'),
    'plan_order': (PlanOrder, '按销售订单创建生产工单并指定设备，quantity默认未计划数量'),
    'release_work_order': (ReleaseWorkOrder, '下达工单，按BOM扣减原料；设备必须可用，库存不足会拒绝'),
    'report_production': (ReportProduction, '生产报工及质量记录；合格品入库，不合格品记录缺陷。累计报工达到目标自动完工'),
    'create_purchase': (CreatePurchase, '创建原料采购单，供应商和单价从原料主数据读取'),
    'receive_purchase': (ReceivePurchase, '采购整单收货入库，同一采购单只能入库一次'),
    'ship_order': (ShipOrder, '按订单发货，扣成品库存；不能超发或超库存'),
}


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex[:10].upper()


def get(db, table, identity):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (identity,)).fetchone()
    if not row:
        raise BusinessError(f'{table} 中不存在 {identity}')
    return dict(row)


def move(db, kind, identity, amount, reason, reference):
    table = 'materials' if kind == 'material' else 'products'
    record = get(db, table, identity)
    if record['stock'] + amount < -0.000001:
        raise BusinessError(f'{record["name"]}库存不足：现有{record["stock"]}，需要{-amount}')
    db.execute(f'UPDATE {table} SET stock=MAX(0,ROUND(stock+?,6)) WHERE id=?', (amount, identity))
    db.execute('INSERT INTO stock_movements(item_type,item_id,quantity,reason,reference_id,created_at) VALUES(?,?,?,?,?,?)', (kind,identity,amount,reason,reference,now()))


def dispatch(db, operation, params):
    if operation not in COMMANDS:
        raise BusinessError('不支持的业务操作')
    p = COMMANDS[operation][0].model_validate(params).model_dump(mode='json')
    if operation == 'create_order':
        get(db,'customers',p['customer_id'])
        product=get(db,'products',p['product_id'])
        identity=uid('SO')
        db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',(identity,p['customer_id'],p['product_id'],p['quantity'],p['unit_price'] or product['price'],p['due_date'],'confirmed',0,now()))
        result=get(db,'orders',identity)
    elif operation == 'plan_order':
        order=get(db,'orders',p['order_id'])
        if order['status']=='shipped':
            raise BusinessError('订单已发货完成，不能再排产')
        machine=get(db,'machines',p['machine_id'])
        if machine['status']=='maintenance':
            raise BusinessError('设备维护中，不能排产')
        committed=db.execute("SELECT COALESCE(SUM(CASE WHEN status='completed' THEN good_qty ELSE quantity-bad_qty END),0) FROM work_orders WHERE order_id=?",(order['id'],)).fetchone()[0]
        remaining=round(order['quantity']-max(committed,order['shipped']),6)
        qty=p['quantity'] if p['quantity'] is not None else remaining
        if qty<=0 or qty>remaining+1e-6:
            raise BusinessError(f'可排产数量为{remaining}米')
        identity=uid('WO')
        db.execute('INSERT INTO work_orders VALUES(?,?,?,?,?,?,?,?,?)',(identity,order['id'],order['product_id'],machine['id'],qty,0,0,'planned',now()))
        db.execute("UPDATE orders SET status='in_production' WHERE id=?",(order['id'],))
        result=get(db,'work_orders',identity)
    elif operation == 'release_work_order':
        work=get(db,'work_orders',p['work_order_id'])
        if work['status']!='planned':
            raise BusinessError('只能下达待开工工单')
        machine=get(db,'machines',work['machine_id'])
        if machine['status']!='available':
            raise BusinessError('设备不可用')
        if db.execute("SELECT 1 FROM work_orders WHERE machine_id=? AND status='running'",(machine['id'],)).fetchone():
            raise BusinessError('设备已有正在执行的工单')
        bom=rows(db,'SELECT * FROM bom WHERE product_id=?',(work['product_id'],))
        if not bom:
            raise BusinessError('产品尚未配置BOM')
        for line in bom:
            move(db,'material',line['material_id'],-round(line['quantity']*work['quantity'],6),'生产领料',work['id'])
        db.execute("UPDATE work_orders SET status='running' WHERE id=?",(work['id'],))
        result=get(db,'work_orders',work['id'])
    elif operation == 'report_production':
        work=get(db,'work_orders',p['work_order_id'])
        if work['status']!='running':
            raise BusinessError('只能对生产中的工单报工')
        total=p['good_qty']+p['bad_qty']
        remaining=round(work['quantity']-work['good_qty']-work['bad_qty'],6)
        if total<=0 or total>remaining+1e-6:
            raise BusinessError(f'本次合格与不合格数量合计必须大于0且不超过{remaining}')
        if p['bad_qty']>0 and not p['defect']:
            raise BusinessError('不合格数量大于0时必须填写缺陷原因')
        identity=uid('PR')
        db.execute('INSERT INTO production_reports VALUES(?,?,?,?,?,?)',(identity,work['id'],p['good_qty'],p['bad_qty'],p['defect'],now()))
        status='completed' if abs(total-remaining)<1e-6 else 'running'
        db.execute('UPDATE work_orders SET good_qty=ROUND(good_qty+?,6),bad_qty=ROUND(bad_qty+?,6),status=? WHERE id=?',(p['good_qty'],p['bad_qty'],status,work['id']))
        if p['good_qty']:
            move(db,'product',work['product_id'],p['good_qty'],'合格品入库',identity)
        result={'id':identity,'work_order':get(db,'work_orders',work['id']),'good_qty':p['good_qty'],'bad_qty':p['bad_qty']}
    elif operation=='create_purchase':
        material=get(db,'materials',p['material_id'])
        identity=uid('PO')
        db.execute('INSERT INTO purchases VALUES(?,?,?,?,?,?,?)',(identity,material['id'],material['supplier_id'],p['quantity'],material['unit_cost'],'ordered',now()))
        result=get(db,'purchases',identity)
    elif operation=='receive_purchase':
        purchase=get(db,'purchases',p['purchase_id'])
        if purchase['status']!='ordered':
            raise BusinessError('采购单已收货，禁止重复入库')
        move(db,'material',purchase['material_id'],purchase['quantity'],'采购入库',purchase['id'])
        db.execute("UPDATE purchases SET status='received' WHERE id=?",(purchase['id'],))
        result=get(db,'purchases',purchase['id'])
    else:
        order=get(db,'orders',p['order_id'])
        if p['quantity']>order['quantity']-order['shipped']+1e-6:
            raise BusinessError('发货量超过订单未发货数量')
        identity=uid('SH')
        move(db,'product',order['product_id'],-p['quantity'],'销售出库',identity)
        db.execute('INSERT INTO shipments VALUES(?,?,?,?)',(identity,order['id'],p['quantity'],now()))
        shipped=round(order['shipped']+p['quantity'],6)
        status='shipped' if abs(shipped-order['quantity'])<1e-6 else 'partial_shipped'
        db.execute('UPDATE orders SET shipped=?,status=? WHERE id=?',(shipped,status,order['id']))
        result={'id':identity,'order':get(db,'orders',order['id']),'quantity':p['quantity']}
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def execute(operation, params, request_id):
    fp=fingerprint([operation,params])
    with transaction() as db:
        cached=db.execute('SELECT * FROM idempotency WHERE request_id=?',(request_id,)).fetchone()
        if cached:
            if cached['fingerprint']!=fp:
                raise BusinessError('相同幂等键对应不同请求')
            return json.loads(cached['result'])
        result=dispatch(db,operation,params)
        encoded=json.dumps(result,ensure_ascii=False)
        db.execute('INSERT INTO audit(operation,request_id,payload,result,created_at) VALUES(?,?,?,?,?)',(operation,request_id,json.dumps(params,ensure_ascii=False),encoded,now()))
        db.execute('INSERT INTO idempotency VALUES(?,?,?)',(request_id,fp,encoded))
        return result


def resolve(value, inputs, outputs):
    if isinstance(value,dict):
        return {k:resolve(v,inputs,outputs) for k,v in value.items()}
    if isinstance(value,list):
        return [resolve(v,inputs,outputs) for v in value]
    if isinstance(value,str) and value.startswith('$'):
        parts=value[1:].split('.')
        obj={'input':inputs,'steps':outputs}
        try:
            for part in parts:
                obj=obj[part]
        except (KeyError,TypeError):
            raise BusinessError(f'流程参数引用无效：{value}')
        return obj
    return value


def execute_workflow(steps, inputs, request_id):
    if not 1<=len(steps)<=12:
        raise BusinessError('流程必须包含1至12步')
    fp=fingerprint([steps,inputs])
    with transaction() as db:
        cached=db.execute('SELECT * FROM idempotency WHERE request_id=?',(request_id,)).fetchone()
        if cached:
            if cached['fingerprint']!=fp:
                raise BusinessError('相同幂等键对应不同流程')
            return json.loads(cached['result'])
        outputs={}
        for step in steps:
            if not step.get('id') or step['id'] in outputs:
                raise BusinessError('流程步骤ID为空或重复')
            params=resolve(step['params'],inputs,outputs)
            result=dispatch(db,step['operation'],params)
            outputs[step['id']]=result
            db.execute('INSERT INTO audit(operation,request_id,payload,result,created_at) VALUES(?,?,?,?,?)',(step['operation'],request_id,json.dumps(params,ensure_ascii=False),json.dumps(result,ensure_ascii=False),now()))
        result={'steps':outputs,'atomic':True}
        db.execute('INSERT INTO idempotency VALUES(?,?,?)',(request_id,fp,json.dumps(result,ensure_ascii=False)))
        return result


CATALOG = {
 'customers':'客户', 'suppliers':'供应商', 'materials':'原料库存，stock/safety_stock单位见unit，unit_cost为元/单位',
 'products':'成品库存，stock单位为米，price元/米', 'bom':'每生产1米所需原料用量，关联product_id和material_id',
 'machines':'设备：available可排产，maintenance维护中；实际忙碌状态查running工单',
 'orders':'销售订单，一单一种产品；quantity/shipped为米；收入=quantity*unit_price，不代表回款',
 'work_orders':'生产工单，quantity为目标米数，good_qty/bad_qty为累计报工；planned/running/completed',
 'production_reports':'报工质检明细，good_qty/bad_qty为本次米数；良品率=SUM(good_qty)/SUM(good_qty+bad_qty)',
 'purchases':'原料采购单，ordered待收货/received已入库',
 'stock_movements':'库存流水，quantity正为入库，负为出库；期初前历史不用于重建库存',
 'shipments':'发货记录，quantity单位米', 'audit':'业务操作审计（含输入与结果）',
}


def catalog():
    db=connect()
    try:
        return [{'table':name,'description':desc,'columns':rows(db,f'PRAGMA table_info({name})')} for name,desc in CATALOG.items()]
    finally:
        db.close()


def query(sql):
    """SQLite VM authorizer, read-only mode, table allowlist and instruction budget."""
    if not isinstance(sql,str) or len(sql)>12000:
        raise BusinessError('查询语句过长或格式错误')
    db=connect()
    db.execute('PRAGMA query_only=ON')
    safe_functions={'sum','avg','count','min','max','round','coalesce','ifnull','nullif','abs','strftime','date','datetime','substr','substring','length','lower','upper','trim','printf','julianday','total','cast','like','row_number','rank','dense_rank'}
    def authorize(action,a,b,database,trigger):
        if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_READ and a in CATALOG:
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_FUNCTION and (b or '').lower() in safe_functions:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    db.set_authorizer(authorize)
    ticks=0
    def budget():
        nonlocal ticks
        ticks+=1
        return int(ticks>1000)
    db.set_progress_handler(budget,1000)
    try:
        cursor=db.execute(sql)
        columns=[d[0] for d in cursor.description or []]
        if len(columns)!=len(set(columns)):
            raise BusinessError('结果包含重复列名，请使用AS别名')
        result=[dict(r) for r in cursor.fetchmany(501)]
        return {'columns':columns,'rows':result[:500],'truncated':len(result)>500,'as_of':now(),'source':'ERP/MES SQLite','limit':500}
    except sqlite3.Error as exc:
        raise BusinessError(f'只读查询失败：{exc}') from exc
    finally:
        db.close()
