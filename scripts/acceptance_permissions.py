"""Real DeepSeek role acceptance on isolated data and ports. No secrets in evidence."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import httpx

ROOT=Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def main():
    assert os.getenv('DEEPSEEK_API_KEY'), 'A real DEEPSEEK_API_KEY is required'
    directory=ROOT/'.runtime'/('permissions-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    app_port,erp_port=free_port(),free_port()
    env=os.environ.copy()
    env.update(APP_PORT=str(app_port),ERP_PORT=str(erp_port),DEMO_DATA_DIR=str(directory/'data'),DEMO_RUNTIME_DIR=str(directory),PYTHONUTF8='1')
    evidence={'status':'running','checks':[],'conversations':[]}
    output=ROOT/'docs'/'permissions-validation.json'
    def save():output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,condition):
        evidence['checks'].append({'name':name,'passed':bool(condition)});save()
        print(('PASS ' if condition else 'FAIL ')+name,flush=True)
        assert condition,name
    with (directory/'supervisor.log').open('wb') as log, httpx.Client(base_url=f'http://127.0.0.1:{app_port}',timeout=35,trust_env=False) as client:
        process=subprocess.Popen([sys.executable,'-m','app.launcher'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            for _ in range(120):
                if process.poll() is not None:raise RuntimeError('Startup failed: '+str(directory))
                try:
                    if client.get('/api/health').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.25)
            accounts={a['username']:a for a in json.loads((directory/'data'/'demo-accounts.json').read_text(encoding='utf-8'))}
            check('Anonymous bootstrap denied',client.get('/api/bootstrap').status_code==401)
            def login(role):
                account=accounts[role]
                client.post('/api/auth/login',json={k:account[k] for k in ('username','password')},headers={'X-Demo-Login':'1'}).raise_for_status()
                bootstrap=client.get('/api/bootstrap').json()
                client.headers['X-Demo-Token']=bootstrap['token']
                return bootstrap
            def chat(role,prompt):
                start=client.post('/api/chat',json={'message':prompt});start.raise_for_status()
                ids=start.json();print('CHAT '+role,flush=True)
                for _ in range(480):
                    run=client.get('/api/runs/'+ids['run_id']);run.raise_for_status();run=run.json()
                    if run['status']!='running':break
                    time.sleep(1)
                evidence['conversations'].append({'role':role,'prompt':prompt,**ids,**run})
                save();check(role+' real AI completed',run['status']=='completed')
                check(role+' real model usage',run['usage'].get('model_calls',0)>0 and run['usage'].get('prompt_tokens',0)>0)
                return run
            login('sales')
            sales=chat('sales','请查询我负责的客户，为C001创建一张P001产品10米、交期2027-01-20的销售订单，使用默认单价。然后统计我负责范围的各产品订单数量，生成柱状图。所有参数已经明确，请直接执行。')
            successful=lambda run,name:[e['payload']['result'] for e in run['events'] if e['kind']=='tool_result' and e['payload']['name']==name and e['payload']['ok']]
            orders=successful(sales,'create_order')
            check('Sales created assigned-customer order',len(orders)==1 and orders[0]['customer_id']=='C001')
            reports=successful(sales,'create_report')
            check('Sales generated actual bar report',bool(reports) and reports[-1]['chart_type']=='bar')
            check('Sales API scope enforced',client.post('/api/query',json={'sql':'SELECT DISTINCT customer_id FROM orders'}).json()['rows']==[{'customer_id':'C001'}])
            sales_report=reports[-1]['id']
            login('production')
            check('Production cannot access sales report',client.get('/api/reports/'+sales_report+'/csv').status_code==404)
            production=chat('production','请先查看当前可用数据目录，按工单统计合格米数，生成柱状图。另外我要所有客户的售价、订单单价、原料采购成本；如果当前目录不提供这些信息，请明确说明，并继续完成生产图表。不要执行任何写操作。')
            check('Production generated actual chart',bool(successful(production,'create_report')))
            catalog=successful(production,'get_catalog')
            check('Production AI catalog hides financial fields',bool(catalog) and all(c['name'] not in ('unit_cost','unit_price','price') for t in catalog[0] for c in t['columns']))
            check('Production direct financial SQL denied',client.post('/api/query',json={'sql':'SELECT unit_cost FROM materials'}).status_code==400)
            login('manager')
            manager=chat('manager','请帮我创建一张C001客户P001产品10米、交期2027-01-20的订单。如果当前岗位没有创建订单能力，请直接明确说明；再查询目前未发货订单的数量。')
            check('Manager has no business writes',not successful(manager,'create_order') and any(e['kind']=='tool_result' and e['payload']['name']=='query_data' and e['payload']['ok'] for e in manager['events']))
            login('admin')
            client.post('/api/shutdown').raise_for_status()
            process.wait(timeout=20)
            check('Admin shutdown closed supervisor',process.returncode==0)
            evidence['status']='passed';save()
        except BaseException:
            evidence['status']='failed';save();raise
        finally:
            if process.poll() is None:
                (directory/'shutdown.request').write_text('acceptance-cleanup')
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)


if __name__=='__main__':main()
