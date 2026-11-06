import copy
import asyncio
import json
import time
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import auth, database, domain, erp as erp_module, server, runtime
from app.adapter import erp, AdapterError
from app.permissions import DEFAULT_ROLES, validate_policy


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setattr(erp_module, 'INTERNAL_TOKEN', 'private-test-token')
    database.init_erp()
    database.init_agent()
    accounts = {a['username']:a for a in json.loads((tmp_path/'demo-accounts.json').read_text(encoding='utf-8'))}
    with TestClient(erp_module.app) as internal, TestClient(server.app) as client:
        async def request(method, path, body=None):
            headers = {'X-Internal-Token':'private-test-token'}
            if path != '/health': headers['X-Actor-Session'] = auth.current_actor()['session_hash']
            response = internal.request(method, path, json=body, headers=headers)
            if response.is_error: raise AdapterError(response.json()['detail'])
            return response.json()
        monkeypatch.setattr(erp, 'request', request)
        def login(role):
            account = accounts[role]
            response = client.post('/api/auth/login', json={k:account[k] for k in ('username','password')}, headers={'X-Demo-Login':'1'})
            assert response.status_code == 200, response.text
            boot = client.get('/api/bootstrap')
            assert boot.status_code == 200, boot.text
            client.headers['X-Demo-Token'] = boot.json()['token']
            return boot.json()
        yield client, internal, login, accounts


def query(client, sql):
    return client.post('/api/query',json={'sql':sql})


def command(client, name, params, request_id=None):
    return client.post('/api/business/'+name,json={'params':params,'request_id':request_id or uuid.uuid4().hex})


def test_anonymous_and_internal_spoofing(env):
    client, internal, login, _ = env
    for path in ['/api/bootstrap','/api/catalog','/api/dashboard','/api/sessions','/api/reports','/api/skills','/api/admin']:
        assert client.get(path, headers={'X-Role':'admin'}).status_code == 401
    assert query(client,'SELECT * FROM orders').status_code == 401
    assert internal.get('/catalog',headers={'X-Internal-Token':'private-test-token','X-Role':'admin'}).status_code == 401
    boot = login('sales')
    assert list(boot['commands']) == ['create_order']
    assert client.get('/api/admin').status_code == 403
    assert client.get('/api/sessions',headers={'X-Demo-User':'warehouse'}).status_code == 401
    assert client.get('/api/bootstrap',headers={'X-Demo-Access':'stale-policy'}).status_code == 401
    assert client.post('/api/shutdown').status_code == 403
    assert client.post('/api/query',json={'sql':'SELECT 1'},headers={'X-Demo-Token':'bad'}).status_code == 403
    assert client.get('/api/bootstrap',headers={'Origin':'https://evil.example'}).status_code == 403


def test_row_column_and_sql_boundaries(env):
    client, _, login, _ = env
    login('sales')
    assert {r['id'] for r in query(client,'SELECT * FROM customers').json()['rows']} == {'C001'}
    assert {r['customer_id'] for r in query(client,'WITH scoped AS (SELECT * FROM main.orders) SELECT * FROM scoped').json()['rows']} == {'C001'}
    assert query(client,"SELECT COUNT(*) n FROM orders WHERE customer_id='C002'").json()['rows'][0]['n'] == 0
    assert query(client,'SELECT * FROM purchases').status_code == 400
    assert query(client,'SELECT * FROM audit').status_code == 400
    assert query(client,'SELECT * FROM sqlite_master').status_code == 400
    assert query(client,"ATTACH DATABASE ':memory:' AS hidden").status_code == 400
    login('production')
    for table, field in [('orders','unit_price'),('products','price'),('materials','unit_cost')]:
        assert field not in query(client,f'SELECT * FROM {table}').json()['columns']
        assert query(client,f'SELECT {field} FROM {table}').status_code == 400
        assert query(client,f'SELECT id FROM {table} WHERE {field}>0').status_code == 400
    assert client.get('/api/dashboard').status_code == 200
    catalog = client.get('/api/catalog').json()
    assert 'unit_price' not in json.dumps(catalog)


def test_writes_scopes_results_and_atomic_workflows(env):
    client, internal, login, _ = env
    login('sales')
    params={'customer_id':'C002','product_id':'P001','quantity':10,'due_date':'2027-01-01'}
    assert command(client,'create_order',params).status_code == 400
    params['customer_id']='C001'
    assert command(client,'create_order',params).status_code == 200
    assert command(client,'create_purchase',{'material_id':'M001','quantity':1}).status_code == 403
    token_hash=auth.token_digest(client.cookies.get(auth.COOKIE))
    before=domain.query('SELECT COUNT(*) n FROM orders')['rows'][0]['n']
    steps=[{'id':'order','operation':'create_order','params':params}, {'id':'purchase','operation':'create_purchase','params':{'material_id':'M001','quantity':1}}]
    denied=internal.post('/workflow',headers={'X-Internal-Token':'private-test-token','X-Actor-Session':token_hash},json={'steps':steps,'inputs':{},'request_id':'atomic-unauthorized'})
    assert denied.status_code == 403
    assert domain.query('SELECT COUNT(*) n FROM orders')['rows'][0]['n']==before
    # A later row-scope failure must roll back an earlier allowed write.
    steps[1]={'id':'other_order','operation':'create_order','params':{**params,'customer_id':'C002'}}
    denied=internal.post('/workflow',headers={'X-Internal-Token':'private-test-token','X-Actor-Session':token_hash},json={'steps':steps,'inputs':{},'request_id':'atomic-row-scope'})
    assert denied.status_code==403
    assert domain.query('SELECT COUNT(*) n FROM orders')['rows'][0]['n']==before
    login('purchasing')
    purchase=command(client,'create_purchase',{'material_id':'M001','quantity':3}).json()
    assert 'unit_cost' in purchase
    login('warehouse')
    receipt=command(client,'receive_purchase',{'purchase_id':purchase['id']}).json()
    assert receipt['status']=='received' and 'unit_cost' not in receipt
    shipment=command(client,'ship_order',{'order_id':'SO0014','quantity':1}).json()
    assert 'unit_price' not in shipment['order']
    login('finance')
    assert not client.get('/api/bootstrap').json()['commands']
    assert command(client,'create_order',params).status_code == 403


def test_private_artifacts_and_revocation(env):
    client, _, login, _=env
    login('sales')
    old_cookie=client.cookies.get(auth.COOKIE)
    owner=auth.resolve_session(auth.token_digest(old_cookie))
    with database.transaction('agent') as db:
        db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',('private-chat','private',database.now(),owner['id'],owner['access_tag']))
        db.execute('INSERT INTO runs(id,session_id,status,created_at) VALUES(?,?,?,?)',('private-run','private-chat','completed',database.now()))
    report=client.post('/api/reports',json={'title':'私有订单','sql':'SELECT * FROM orders'}).json()
    assert client.get('/api/reports/'+report['id']+'/csv').status_code==200
    login('warehouse')
    for path in ['/api/sessions/private-chat','/api/runs/private-run','/api/reports/'+report['id'],'/api/reports/'+report['id']+'/csv']:
        assert client.get(path).status_code==404
    assert client.post('/api/chat',json={'session_id':'private-chat','message':'继续'}).status_code==404
    assert client.get('/api/sessions').json()==[]
    login('admin')
    data=client.get('/api/admin').json()
    user=next(u for u in data['users'] if u['id']=='sales')
    user.update(customer_ids=['C002'],active=True)
    assert client.put('/api/admin/users/sales',json=user).status_code==200
    with pytest.raises(HTTPException): auth.resolve_session(auth.token_digest(old_cookie))
    login('sales')
    assert client.get('/api/sessions').json()==[]
    assert client.get('/api/reports').json()==[]
    assert {r['id'] for r in query(client,'SELECT * FROM customers').json()['rows']}=={'C002'}
    cookie=client.cookies.get(auth.COOKIE)
    assert client.post('/api/auth/logout').status_code==200
    with pytest.raises(HTTPException): auth.resolve_session(auth.token_digest(cookie))


def test_admin_updates_skills_and_tool_visibility(env):
    client, _, login, accounts=env
    login('production')
    context=auth.session_context.set(auth.token_digest(client.cookies.get(auth.COOKIE)))
    try:
        tools={t['function']['name'] for t in runtime.tool_definitions()}
        assert 'create_order' not in tools and 'create_purchase' not in tools
        assert 'report_production' in tools
    finally: auth.session_context.reset(context)
    assert 'order-to-production' not in {s['id'] for s in client.get('/api/skills').json()}
    assert client.get('/api/admin').status_code==403
    login('admin')
    data=client.get('/api/admin').json()
    admin=next(u for u in data['users'] if u['id']=='admin');admin.update(active=False)
    assert client.put('/api/admin/users/admin',json=admin).status_code==400
    role=next(r for r in data['roles'] if r['id']=='finance')
    role['policy']['tables']['orders'].remove('unit_price')
    assert client.put('/api/admin/roles/finance',json=role).status_code==200
    assert client.put('/api/admin/roles/admin',json=role).status_code==400
    login('finance')
    assert 'unit_price' not in query(client,'SELECT * FROM orders').json()['columns']
    login('admin')
    new={'username':'sales_two','name':'第二销售','role_id':'sales','customer_ids':['C003'],'active':True,'password':'A-valid-test-password'}
    assert client.put('/api/admin/users/new-sales',json=new).status_code==200
    assert client.post('/api/auth/login',json={'username':'sales_two','password':new['password']},headers={'X-Demo-Login':'1'}).status_code==200
    assert 'password_hash' not in json.dumps(data)
    db=database.connect('agent')
    try:
        stored=db.execute("SELECT password_hash FROM users WHERE id='admin'").fetchone()[0]
        assert accounts['admin']['password'] not in stored
        db.execute('UPDATE auth_sessions SET expires=?',(time.time()-1,));db.commit()
    finally: db.close()
    assert client.get('/api/bootstrap').status_code==401


def test_login_throttle_and_policy_validation(env):
    client, _, _, _=env
    for _ in range(10):
        assert client.post('/api/auth/login',headers={'X-Demo-Login':'1'},json={'username':'sales','password':'incorrect'}).status_code==401
    assert client.post('/api/auth/login',headers={'X-Demo-Login':'1'},json={'username':'sales','password':'incorrect'}).status_code==429
    policy=copy.deepcopy(DEFAULT_ROLES['sales'][1]);policy['commands'].append('create_purchase')
    with pytest.raises(ValueError):validate_policy(policy)


def test_revocation_stops_inflight_model_result(env,monkeypatch):
    client, _, login, _=env
    login('sales')
    token_hash=auth.token_digest(client.cookies.get(auth.COOKIE))
    context=auth.session_context.set(token_hash)
    try:
        owner,tag=auth.artifact_owner()
        with database.transaction('agent') as db:
            db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',('inflight-chat','inflight',database.now(),owner,tag))
            db.execute('INSERT INTO runs(id,session_id,status,created_at) VALUES(?,?,?,?)',('inflight-run','inflight-chat','running',database.now()))
        async def revoke_while_model_is_busy(messages):
            with database.transaction('agent') as db:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(token_hash,))
            return {'choices':[{'message':{'role':'assistant','content':'SHOULD_NOT_PERSIST'}}],'usage':{}}
        monkeypatch.setattr(runtime,'model_call',revoke_while_model_is_busy)
        asyncio.run(runtime.run_agent('inflight-run','inflight-chat'))
        db=database.connect('agent')
        try:
            assert db.execute("SELECT status FROM runs WHERE id='inflight-run'").fetchone()[0]=='failed'
            assert not db.execute("SELECT 1 FROM messages WHERE content LIKE '%SHOULD_NOT_PERSIST%'").fetchone()
        finally:db.close()
    finally:auth.session_context.reset(context)
