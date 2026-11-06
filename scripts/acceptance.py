"""Real DeepSeek -> Agent -> private HTTP adapter -> ERP/MES acceptance.

Runs isolated services and databases. Never mocks the model or modifies the demo DB.
Writes a reviewable transcript to docs/acceptance-result.json, including model usage.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime,timedelta,timezone
import httpx

ROOT=Path(__file__).resolve().parent.parent
BASE='http://127.0.0.1:8875'
OUTPUT=ROOT/'docs'/'acceptance-result.json'
evidence={'started_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'model':'','checks':[],'conversations':[],'status':'running'}


def save():
    OUTPUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


def check(name,condition,details=None):
    evidence['checks'].append({'name':name,'passed':bool(condition),'details':details})
    save()
    print(('PASS ' if condition else 'FAIL ')+name,flush=True)
    assert condition,name


def port_open(port):
    with socket.socket() as s:
        s.settimeout(.3)
        return s.connect_ex(('127.0.0.1',port))==0


def main():
    if not os.getenv('DEEPSEEK_API_KEY'):
        raise RuntimeError('DEEPSEEK_API_KEY is required; there is no mock fallback.')
    runtime=ROOT/'.runtime'/('acceptance-'+uuid.uuid4().hex[:8])
    runtime.mkdir(parents=True)
    env=os.environ.copy()
    env.update({'APP_PORT':'8875','ERP_PORT':'8876','DEMO_DATA_DIR':str(runtime/'data'),'DEMO_RUNTIME_DIR':str(runtime),'PYTHONUNBUFFERED':'1'})
    log=(runtime/'supervisor.log').open('ab')
    supervisor=None
    client=httpx.Client(base_url=BASE,timeout=35,trust_env=False)
    def launch():
        p=subprocess.Popen([sys.executable,'-m','app.launcher'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(80):
            if p.poll() is not None:
                raise RuntimeError('Acceptance service failed; see '+str(runtime))
            try:
                health=client.get('/api/health')
                if health.status_code==200:
                    bootstrap=client.get('/api/bootstrap').json()
                    client.headers['X-Demo-Token']=bootstrap['token']
                    evidence['model']=bootstrap['model']
                    return p
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        raise RuntimeError('Acceptance service startup timeout')
    def request(method,path,body=None):
        response=client.request(method,path,json=body)
        response.raise_for_status()
        return response.json()
    def query(sql):return request('POST','/api/query',{'sql':sql})['rows']
    def scalar(sql):return next(iter(query(sql)[0].values()))
    def chat(name,prompt,session=None):
        start=time.monotonic()
        run=request('POST','/api/chat',{'message':prompt,'session_id':session})
        print('CHAT '+name+' '+run['run_id'],flush=True)
        conversation={'name':name,'prompt':prompt,**run,'events':[]}
        evidence['conversations'].append(conversation)
        after=0
        for _ in range(540):
            data=request('GET','/api/runs/'+run['run_id']+'?after='+str(after))
            for event in data['events']:
                after=event['id']
                conversation['events'].append(event)
                if event['kind']=='tool_result':
                    print('  TOOL '+event['payload']['name']+' '+str(event['payload']['ok']),flush=True)
            if data['status']!='running':
                conversation.update({'status':data['status'],'usage':data['usage'],'elapsed_seconds':round(time.monotonic()-start,2)})
                save()
                check(name+' completed with real AI',data['status']=='completed',data.get('error'))
                return conversation
            time.sleep(1)
        raise RuntimeError('Real AI run timed out')
    def results(conversation,name):
        return [e['payload']['result'] for e in conversation['events'] if e['kind']=='tool_result' and e['payload']['name']==name and e['payload']['ok']]
    try:
        supervisor=launch()
        check('ERP rejects requests without private adapter token',httpx.get('http://127.0.0.1:8876/health',trust_env=False).status_code==401)
        check('No MCP endpoint',client.get('/mcp').status_code==404)
        check('Mutation rejects missing browser token',httpx.post(BASE+'/api/query',json={'sql':'SELECT 1'},trust_env=False).status_code==403)
        check('Mutation rejects cross-origin requests',client.post('/api/query',json={'sql':'SELECT 1'},headers={'Origin':'https://evil.example'}).status_code==403)
        check('Frontend static assets served',all(client.get(path).status_code==200 for path in ['/','/static/app.js','/static/styles.css','/static/vendor/echarts.min.js']))
        check('Integrated seeded business data',scalar('SELECT COUNT(*) FROM orders')==18 and scalar('SELECT COUNT(*) FROM materials')==4)
        report=chat('analysis_and_charts','请查询各产品累计订单金额和累计生产良品率，金额和报工分开聚合以免重复计数。生成三份保存的报表：产品订单金额柱状图、产品订单金额饼图、产品良品率明细表。每份使用真实SQL数据，不要只给文字表格。最后说明订单金额不是回款。')
        saved=results(report,'create_report')
        check('AI persisted bar, pie and table reports',{'bar','pie','table'}<={r['chart_type'] for r in saved})
        expected={r['name']:r['amount'] for r in query('SELECT p.name,SUM(o.quantity*o.unit_price) AS amount FROM orders o JOIN products p ON p.id=o.product_id GROUP BY p.id')}
        numeric_values=[v for r in saved if r['chart_type']=='bar' for row in r['data']['rows'] for v in row.values() if isinstance(v,(int,float))]
        check('AI chart amounts match independent SQL aggregation',all(v in numeric_values for v in expected.values()),expected)
        for r in saved:
            check('Report CSV export '+r['chart_type'],client.get('/api/reports/'+r['id']+'/csv').status_code==200)
        old=scalar("SELECT stock FROM materials WHERE id='M002'")
        purchase=chat('purchase_skill','已收到原料M002再生涤纶丝400kg，确认实际已到货。请读取并运行purchase-receive技能，创建采购单并立即入库，核对库存变化。')
        check('AI used configured purchase workflow',bool(results(purchase,'run_skill')))
        check('Purchase workflow changed ERP stock exactly once',scalar("SELECT stock FROM materials WHERE id='M002'")==old+400)
        check('Purchase is received',scalar("SELECT COUNT(*) FROM purchases WHERE status='received'")==1)
        old_cotton=scalar("SELECT stock FROM materials WHERE id='M001'")
        due=(datetime.now(timezone(timedelta(hours=8)))+timedelta(days=10)).date().isoformat()
        production=chat('order_production_skill',f'请读取并执行order-to-production技能：客户C001，产品P001，数量120米，交期{due}，设备MC02。明确授权创建订单、排产并下达领料。完成后告诉我订单号和工单号。')
        check('AI used configured production workflow',bool(results(production,'run_skill')))
        new_orders=query("SELECT * FROM orders WHERE id LIKE 'SO-%'")
        check('AI created one real sales order',len(new_orders)==1)
        order=new_orders[0]
        works=query("SELECT * FROM work_orders WHERE order_id='"+order['id']+"'")
        check('Work order is running',len(works)==1 and works[0]['status']=='running')
        check('BOM material consumed correctly',abs(scalar("SELECT stock FROM materials WHERE id='M001'")-(old_cotton-21.6))<1e-6)
        finished=scalar("SELECT stock FROM products WHERE id='P001'")
        fulfillment=chat('multi_turn_quality_shipping','对刚才创建的那张工单报工：合格118米，不合格2米，原因色差。然后按刚才的销售订单发货118米。请实际执行，并核对工单、订单及成品库存。',production['session_id'])
        check('AI multi-turn recovered business context',bool(results(fulfillment,'report_production')) and bool(results(fulfillment,'ship_order')))
        work=query("SELECT * FROM work_orders WHERE id='"+works[0]['id']+"'")[0]
        check('Quality and production persisted',work['good_qty']==118 and work['bad_qty']==2 and work['status']=='completed')
        check('Shipping persisted without inflating stock',scalar("SELECT stock FROM products WHERE id='P001'")==finished and scalar("SELECT shipped FROM orders WHERE id='"+order['id']+"'")==118)
        completion=chat('rework_and_complete','请补足刚才订单剩余的2米：在MC02创建2米补产工单并下达，报工合格2米不合格0，再发货2米使订单完成。请依次实际执行。',production['session_id'])
        check('Replacement production completes order',scalar("SELECT status FROM orders WHERE id='"+order['id']+"'")=='shipped')
        counts={r['operation']:r['n'] for r in query('SELECT operation,COUNT(*) AS n FROM audit GROUP BY operation')}
        check('Workflow operations are auditable',counts=={'create_purchase':1,'receive_purchase':1,'create_order':1,'plan_order':2,'release_work_order':2,'report_production':2,'ship_order':2},counts)
        # Install a new configurable instruction skill; prove AI reads and follows it.
        custom={'id':'acceptance-quality','name':'质量验收技能','description':'按缺陷汇总不合格米数，生成质量明细表。','enabled':True,'instructions':'必须查询production_reports，按defect汇总SUM(bad_qty)，排除bad_qty=0的记录。保存一份title为质量验收汇总的table报表，说明计量单位为米。','inputs':{},'steps':[]}
        request('PUT','/api/skills/acceptance-quality',custom)
        custom_run=chat('custom_configurable_skill','请读取并使用acceptance-quality技能，严格按照技能指令完成并保存报表。')
        check('AI read newly installed skill',any(r.get('id')=='acceptance-quality' for r in results(custom_run,'read_skill')))
        check('Custom skill produced expected report',any(r['title']=='质量验收汇总' for r in results(custom_run,'create_report')))
        custom['enabled']=False
        request('PUT','/api/skills/acceptance-quality',custom)
        disabled=chat('disabled_skill','请使用acceptance-quality技能。如果该技能已禁用，请明确告诉我，停止执行，不要创建任何报表。')
        check('Disabled skill cannot run',not results(disabled,'run_skill') and not results(disabled,'create_report'))
        # Exercise all online drawing representations through the same frontend-facing API.
        for chart_type in ['table','pivot','bar','line','area','pie','scatter','heatmap']:
            data=request('POST','/api/reports',{'title':'API验证-'+chart_type,'chart_type':chart_type,'rows':[{'x':1,'group':'A','value':12},{'x':2,'group':'B','value':18}],'x':'x','y':['value'],'group':'group'})
            check('Online report API '+chart_type,data['chart_type']==chart_type and len(data['data']['rows'])==2)
        check('Read-only query rejects SQL writes',client.post('/api/query',json={'sql':"UPDATE materials SET stock=999999"}).status_code==400)
        saved_count=len(request('GET','/api/reports'))
        session_count=len(request('GET','/api/sessions'))
        request('POST','/api/shutdown',{})
        supervisor.wait(timeout=20)
        check('One-click shutdown closes both servers',not port_open(8875) and not port_open(8876))
        supervisor=launch()
        check('Reports and chats survive restart',len(request('GET','/api/reports'))==saved_count and len(request('GET','/api/sessions'))==session_count)
        check('ERP business state survives restart',scalar("SELECT status FROM orders WHERE id='"+order['id']+"'")=='shipped')
        request('POST','/api/shutdown',{})
        supervisor.wait(timeout=20)
        check('Restarted demo shuts down cleanly',not port_open(8875) and not port_open(8876))
        evidence['status']='passed'
    except BaseException as exc:
        evidence['status']='failed'
        evidence['error']=str(exc)
        raise
    finally:
        evidence['finished_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
        save()
        if supervisor and supervisor.poll() is None:
            (runtime/'shutdown.request').write_text('acceptance-cleanup')
            try:supervisor.wait(timeout=20)
            except subprocess.TimeoutExpired:supervisor.terminate()
        client.close()
        log.close()
        print('Evidence: '+str(OUTPUT),flush=True)


if __name__=='__main__':
    main()
