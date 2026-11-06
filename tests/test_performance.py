import asyncio
import json
import httpx
import pytest
from test_permissions import env
from app import auth,database,domain,server,runtime


@pytest.mark.parametrize('sql,tables',[
    ('SELECT 1 n',set()),
    ('SELECT COUNT(*) n FROM orders',{'orders'}),
    ('WITH o AS (SELECT * FROM main.orders) SELECT p.name,SUM(o.quantity) n FROM o JOIN products p ON o.product_id=p.id GROUP BY p.name',{'orders','products'}),
    ('SELECT id FROM orders UNION SELECT order_id FROM shipments',{'orders','shipments'}),
    ('SELECT id FROM products WHERE EXISTS (SELECT 1 FROM orders WHERE product_id=products.id)',{'orders','products'}),
])
def test_sql_compiler_only_materializes_referenced_authorized_tables(env,monkeypatch,sql,tables):
    client,_,login,_=env
    login('sales')
    copied=[]
    original=domain.projected_db
    def trace(source,actor,queries=None):
        source.set_trace_callback(lambda statement:copied.append(statement))
        return original(source,actor,queries)
    monkeypatch.setattr(domain,'projected_db',trace)
    result=client.post('/api/query',json={'sql':sql})
    assert result.status_code==200,result.text
    selects=[s for s in copied if s.startswith('SELECT ')]
    assert len(selects)==len(tables)
    for table in tables:assert any(f' FROM {table}' in s for s in selects)
    if 'orders' in tables:assert all('WHERE' in s and "'C001'" in s for s in selects if ' FROM orders' in s)


def test_sql_budget_and_hidden_columns_survive_planning(env):
    client,_,login,_=env
    login('production')
    for sql in ['SELECT unit_price FROM main.orders',"WITH orders AS (SELECT * FROM main.orders) SELECT unit_price FROM orders",'SELECT * FROM sqlite_master','SELECT COUNT(*) FROM sqlite_master','SELECT COUNT(*) FROM idempotency','PRAGMA table_info(orders)',"WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n"]:
        assert client.post('/api/query',json={'sql':sql}).status_code==400
    assert client.post('/api/query',json={'sql':"SELECT printf('%2000000s','x') huge"}).status_code in (200,400)
    result=client.post('/api/query',json={'sql':"WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<500) SELECT printf('%10000s','x') value FROM n"}).json()
    assert result['truncated'] and 0<len(result['rows'])<500


def test_history_and_events_paginate_without_losing_report_call_context(env):
    client,_,login,_=env
    login('sales')
    actor=auth.resolve_session(auth.token_digest(client.cookies.get(auth.COOKIE)))
    with database.transaction('agent') as db:
        db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',('paged','pages',database.now(),actor['id'],actor['access_tag']))
        db.execute('INSERT INTO runs(id,session_id,status,created_at) VALUES(?,?,?,?)',('paged-run','paged','completed',database.now()))
        for i in range(300):
            body={'role':'assistant','content':str(i)}
            if i==99:body={'role':'assistant','content':None,'tool_calls':[{'id':'chart-call','function':{'name':'create_report'}}]}
            if i==100:body={'role':'tool','tool_call_id':'chart-call','content':'{}'}
            db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',('paged',body['role'],json.dumps(body),database.now()))
        db.executemany('INSERT INTO events(run_id,kind,payload,created_at) VALUES(?,?,?,?)',(('paged-run','status','{}',database.now()) for _ in range(450)))
    first=client.get('/api/sessions/paged').json()
    assert len(first['messages'])==200 and first['has_more']
    assert first['messages'][0]['tool_name']=='create_report'
    previous=client.get('/api/sessions/paged',params={'before':first['before_id']}).json()
    assert len(previous['messages'])==100 and not previous['has_more']
    ids=[m['id'] for m in previous['messages']+first['messages']]
    assert ids==sorted(set(ids)) and len(ids)==300
    after=0;seen=[]
    while True:
        page=client.get('/api/runs/paged-run',params={'after':after}).json()
        assert len(page['events'])<=200
        seen.extend(e['id'] for e in page['events']);after=seen[-1]
        if not page['has_more']:break
    assert len(seen)==450 and seen==sorted(set(seen))
    login('production')
    assert client.get('/api/sessions/paged',params={'before':first['before_id']}).status_code==404
    assert client.get('/api/runs/paged-run',params={'after':after}).status_code==404


def test_capacity_is_atomic_and_rejected_chats_leave_no_rows(env,monkeypatch):
    client,_,login,_=env
    async def stalled(*args):await asyncio.Event().wait()
    monkeypatch.setattr(server,'run_agent',stalled)
    monkeypatch.setattr(server,'MAX_AGENT_RUNS',3)
    monkeypatch.setattr(server,'MAX_USER_RUNS',2)
    login('sales')
    for _ in range(2):assert client.post('/api/chat',json={'message':'hold'}).status_code==202
    denied=client.post('/api/chat',json={'message':'over user limit'})
    assert denied.status_code==429 and denied.headers['retry-after']=='5'
    login('production')
    assert client.post('/api/chat',json={'message':'hold'}).status_code==202
    assert client.post('/api/chat',json={'message':'over global limit'}).status_code==429
    db=database.connect('agent')
    try:
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==3
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==3
    finally:db.close()


def test_password_hash_does_not_hold_the_database_writer_lock(env,monkeypatch):
    client,_,login,_=env
    original=auth.password_hash
    checked=[]
    def hash_without_lock(password,salt=None):
        db=database.connect('agent')
        try:
            db.execute('PRAGMA busy_timeout=50')
            db.execute('BEGIN IMMEDIATE')
            checked.append(True)
            db.rollback()
        finally:db.close()
        return original(password,salt)
    monkeypatch.setattr(auth,'password_hash',hash_without_lock)
    login('sales')
    assert checked==[True]


def test_auth_io_runs_off_event_loop_and_heartbeat_skips_erp(env,monkeypatch):
    client,_,login,_=env
    login('sales')
    original=auth.resolve_session
    loops=[]
    def resolve(token):
        try:asyncio.get_running_loop();loops.append(True)
        except RuntimeError:loops.append(False)
        return original(token)
    async def no_erp(*args,**kwargs):raise AssertionError('session heartbeat should not call ERP')
    monkeypatch.setattr(auth,'resolve_session',resolve)
    monkeypatch.setattr(server.erp,'request',no_erp)
    assert client.get('/api/auth/session').status_code==200
    assert loops==[False]


def test_model_client_reused_with_fresh_role_tools(env,monkeypatch):
    client,_,login,_=env
    identities=[]
    for role in ['sales','production']:
        login(role);identities.append(auth.token_digest(client.cookies.get(auth.COOKIE)))
    requests=[]
    async def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'ok'}}]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as provider:
            monkeypatch.setattr(runtime,'_model_client',provider)
            monkeypatch.setenv('DEEPSEEK_API_KEY','unit-test-placeholder')
            async def call(token):
                context=auth.session_context.set(token)
                try:await runtime.model_call([{'role':'user','content':'test'}])
                finally:auth.session_context.reset(context)
            await asyncio.gather(*(call(token) for token in identities))
            assert not provider.is_closed
    asyncio.run(scenario())
    offered=[{t['function']['name'] for t in r['tools']} for r in requests]
    assert any('create_order' in names and 'report_production' not in names for names in offered)
    assert any('report_production' in names and 'create_order' not in names for names in offered)


def test_large_history_rejected_before_deserialization(env,monkeypatch):
    client,_,login,_=env
    login('sales')
    context=auth.session_context.set(auth.token_digest(client.cookies.get(auth.COOKIE)))
    try:
        with database.transaction('agent') as db:
            db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',('large','large',database.now(),*auth.artifact_owner()))
            db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',('large','user','x'*230000,database.now()))
        # Deliberately invalid JSON: the size guard must run before decoding it.
        with pytest.raises(ValueError,match='较长'):runtime.load_history('large')
        with pytest.raises(ValueError,match='上下文预算'):
            runtime.model_payload([{'role':'tool','tool_call_id':'huge-result','content':'x'*260000}])
    finally:auth.session_context.reset(context)


def test_payload_page_bounds_bytes_and_always_advances(env):
    db=database.connect('agent')
    try:
        db.execute('CREATE TEMP TABLE payloads(id INTEGER,content TEXT)')
        db.executemany('INSERT INTO payloads VALUES(?,?)',[(1,'a'*20),(2,'b'*20),(3,'c'*200)])
        page,more=database.payload_page(db,'SELECT * FROM payloads ORDER BY id',(),'content',max_bytes=30)
        assert [r['id'] for r in page]==[1] and more
        page,more=database.payload_page(db,'SELECT * FROM payloads WHERE id>2 ORDER BY id',(),'content',max_bytes=30)
        assert [r['id'] for r in page]==[3] and not more
    finally:db.close()
