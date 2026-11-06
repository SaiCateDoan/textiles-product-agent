import json
import sqlite3
import uuid
import asyncio
import pytest
from pydantic import ValidationError
from app import database,domain,skills


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATA',tmp_path)
    database.init_erp()
    database.init_agent()


def execute(name,**params):
    return domain.execute(name,params,uuid.uuid4().hex)


def scalar(sql):
    return next(iter(domain.query(sql)['rows'][0].values()))


def new_order(quantity=100):
    return execute('create_order',customer_id='C001',product_id='P001',quantity=quantity,due_date='2026-12-20')


def test_full_lifecycle_and_reject_rework():
    stock=scalar("SELECT stock FROM materials WHERE id='M001'")
    finished=scalar("SELECT stock FROM products WHERE id='P001'")
    order=new_order()
    work=execute('plan_order',order_id=order['id'],machine_id='MC02')
    execute('release_work_order',work_order_id=work['id'])
    assert scalar("SELECT stock FROM materials WHERE id='M001'")==pytest.approx(stock-18)
    result=execute('report_production',work_order_id=work['id'],good_qty=98,bad_qty=2,defect='色差')
    assert result['work_order']['status']=='completed'
    assert scalar("SELECT stock FROM products WHERE id='P001'")==finished+98
    shipped=execute('ship_order',order_id=order['id'],quantity=98)
    assert shipped['order']['status']=='partial_shipped'
    rework=execute('plan_order',order_id=order['id'],machine_id='MC02')
    assert rework['quantity']==2
    execute('release_work_order',work_order_id=rework['id'])
    execute('report_production',work_order_id=rework['id'],good_qty=2)
    assert execute('ship_order',order_id=order['id'],quantity=2)['order']['status']=='shipped'
    assert scalar("SELECT stock FROM products WHERE id='P001'")==finished


def test_receipt_idempotency_and_conflicts():
    old=scalar("SELECT stock FROM materials WHERE id='M002'")
    purchase=execute('create_purchase',material_id='M002',quantity=200)
    args={'purchase_id':purchase['id']}
    first=domain.execute('receive_purchase',args,'same-request-001')
    assert domain.execute('receive_purchase',args,'same-request-001')==first
    assert scalar("SELECT stock FROM materials WHERE id='M002'")==old+200
    with pytest.raises(domain.BusinessError):
        execute('receive_purchase',**args)
    with pytest.raises(domain.BusinessError):
        domain.execute('create_purchase',{'material_id':'M002','quantity':300},'same-request-001')


def test_planning_accounts_for_orders_shipped_from_existing_stock():
    order=new_order()
    execute('ship_order',order_id=order['id'],quantity=60)
    work=execute('plan_order',order_id=order['id'],machine_id='MC02')
    assert work['quantity']==40


def test_workflow_rolls_back_all_steps_on_shortage():
    skill=skills.get_skill('order-to-production')
    before={table:scalar(f'SELECT COUNT(*) FROM {table}') for table in ['orders','work_orders','audit','stock_movements']}
    stock=scalar("SELECT stock FROM materials WHERE id='M001'")
    # P003: cotton is sufficient, dye is not. Even the first material deduction must roll back.
    inputs={'customer_id':'C001','product_id':'P003','quantity':5000,'due_date':'2026-12-20','machine_id':'MC03'}
    with pytest.raises(domain.BusinessError,match='库存不足'):
        domain.execute_workflow(skill['steps'],inputs,'workflow-rollback-test')
    assert scalar("SELECT stock FROM materials WHERE id='M001'")==stock
    for table,count in before.items():
        assert scalar(f'SELECT COUNT(*) FROM {table}')==count


def test_workflow_success_idempotency():
    skill=skills.get_skill('purchase-receive')
    args={'material_id':'M003','quantity':50}
    first=domain.execute_workflow(skill['steps'],args,'workflow-success-test')
    assert domain.execute_workflow(skill['steps'],args,'workflow-success-test')==first
    assert scalar("SELECT stock FROM materials WHERE id='M003'")==130
    assert scalar('SELECT COUNT(*) FROM purchases')==1


def test_machine_overbooking_and_invalid_transitions():
    first=new_order();second=new_order()
    work1=execute('plan_order',order_id=first['id'],machine_id='MC01')
    work2=execute('plan_order',order_id=second['id'],machine_id='MC01')
    with pytest.raises(domain.BusinessError):
        execute('report_production',work_order_id=work1['id'],good_qty=100)
    execute('release_work_order',work_order_id=work1['id'])
    with pytest.raises(domain.BusinessError,match='已有'):
        execute('release_work_order',work_order_id=work2['id'])
    with pytest.raises(domain.BusinessError):
        execute('release_work_order',work_order_id=work1['id'])
    with pytest.raises(domain.BusinessError):
        execute('plan_order',order_id=second['id'],machine_id='MC04')


def test_invalid_quantities_no_writes():
    count=scalar('SELECT COUNT(*) FROM orders')
    for quantity in [-1,0,float('nan'),float('inf')]:
        with pytest.raises(ValidationError):
            new_order(quantity)
    assert scalar('SELECT COUNT(*) FROM orders')==count
    order=new_order()
    with pytest.raises(domain.BusinessError):
        execute('ship_order',order_id=order['id'],quantity=101)
    work=execute('plan_order',order_id=order['id'],machine_id='MC02')
    execute('release_work_order',work_order_id=work['id'])
    with pytest.raises(domain.BusinessError):
        execute('report_production',work_order_id=work['id'],good_qty=101)
    with pytest.raises(domain.BusinessError):
        execute('report_production',work_order_id=work['id'],good_qty=99,bad_qty=1)


@pytest.mark.parametrize('sql',[
    'DELETE FROM materials',"UPDATE materials SET stock=999",'PRAGMA table_info(materials)',
    "ATTACH DATABASE ':memory:' AS other",'SELECT * FROM idempotency','SELECT * FROM sqlite_master',
    "SELECT load_extension('evil')",'SELECT 1; DELETE FROM orders',
    "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n",
])
def test_read_only_query_authorizer(sql):
    with pytest.raises(domain.BusinessError):domain.query(sql)


def test_query_aggregation_and_limit():
    result=domain.query('SELECT p.name,ROUND(SUM(o.quantity*o.unit_price),2) AS amount FROM orders o JOIN products p ON p.id=o.product_id GROUP BY p.id,p.name')
    assert len(result['rows'])==3
    capped=domain.query('SELECT a.id AS first,b.id AS second,c.id AS third FROM orders a CROSS JOIN orders b CROSS JOIN orders c')
    assert len(capped['rows'])==500 and capped['truncated']
    with pytest.raises(domain.BusinessError):domain.query('SELECT o.id,p.id FROM orders o JOIN products p ON o.product_id=p.id')


def test_skill_configuration_is_enforced():
    skill=skills.get_skill('purchase-receive')
    skill['enabled']=False
    skills.save_skill(skill)
    with pytest.raises(ValueError,match='禁用'):skills.get_skill('purchase-receive')
    skill['steps'][0]['operation']='execute_shell'
    with pytest.raises(ValidationError):skills.save_skill(skill)
    skill=skills.get_skill('order-to-production')
    skill['steps'][0]['params']['customer_id']='$steps.future.id'
    with pytest.raises(ValidationError):skills.save_skill(skill)


def test_restart_repairs_unfinished_tool_call_history():
    with database.transaction('agent') as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?)',('test-session','测试',database.now()))
        db.execute("INSERT INTO runs(id,session_id,status,created_at) VALUES('test-run','test-session','running',?)",(database.now(),))
        message={'role':'assistant','content':None,'tool_calls':[{'id':'call-unknown','type':'function','function':{'name':'create_order','arguments':'{}'}}]}
        db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',('test-session','assistant',json.dumps(message),database.now()))
    database.init_agent()
    db=database.connect('agent')
    assert db.execute("SELECT status FROM runs WHERE id='test-run'").fetchone()[0]=='interrupted'
    messages=[json.loads(r['content']) for r in db.execute('SELECT content FROM messages ORDER BY id')]
    db.close()
    assert messages[1]['role']=='tool' and messages[1]['tool_call_id']=='call-unknown'
    assert messages[2]['role']=='assistant'


@pytest.mark.parametrize('kind',['table','pivot','bar','line','area','pie','scatter','heatmap'])
def test_manual_reports_persist_all_chart_types(kind):
    from app.reports import create_report,ReportSpec,get_report
    created=asyncio.run(create_report(ReportSpec(title='测试',chart_type=kind,rows=[{'x':1,'g':'A','n':4}],x='x',y=['n'],group='g')))
    saved=get_report(created['id'])
    assert saved['chart_type']==kind and saved['data']['rows'][0]['n']==4


def test_report_validation_and_csv_formula_neutralization():
    from app.reports import create_report,ReportSpec
    from app.server import report_csv
    with pytest.raises(ValueError,match='数值列'):
        asyncio.run(create_report(ReportSpec(title='错误',chart_type='bar',rows=[{'x':'A','n':'bad'}],x='x',y=['n'])))
    created=asyncio.run(create_report(ReportSpec(title='导出',rows=[{'=header':'=SUM(1,2)'}])))
    csv=report_csv(created['id']).body.decode('utf-8-sig')
    assert "'=header" in csv and "'=SUM(1,2)" in csv
