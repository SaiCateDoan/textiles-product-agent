import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from .config import DATA


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def connect(name='erp'):
    db = sqlite3.connect(DATA / f'{name}.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db


@contextmanager
def transaction(name='erp'):
    db = connect(name)
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def init_erp():
    db = connect()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,name TEXT NOT NULL,contact TEXT);
    CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY,name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL,stock REAL NOT NULL CHECK(stock>=0),safety_stock REAL NOT NULL,unit_cost REAL NOT NULL,supplier_id TEXT REFERENCES suppliers(id));
    CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT NOT NULL,spec TEXT,unit TEXT NOT NULL,price REAL NOT NULL,stock REAL NOT NULL CHECK(stock>=0));
    CREATE TABLE IF NOT EXISTS bom(product_id TEXT REFERENCES products(id),material_id TEXT REFERENCES materials(id),quantity REAL NOT NULL,PRIMARY KEY(product_id,material_id));
    CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY,name TEXT NOT NULL,workshop TEXT NOT NULL,status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,customer_id TEXT REFERENCES customers(id),product_id TEXT REFERENCES products(id),quantity REAL NOT NULL,unit_price REAL NOT NULL,due_date TEXT NOT NULL,status TEXT NOT NULL,shipped REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS work_orders(id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(id),product_id TEXT REFERENCES products(id),machine_id TEXT REFERENCES machines(id),quantity REAL NOT NULL,good_qty REAL NOT NULL DEFAULT 0,bad_qty REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS production_reports(id TEXT PRIMARY KEY,work_order_id TEXT REFERENCES work_orders(id),good_qty REAL NOT NULL,bad_qty REAL NOT NULL,defect TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS purchases(id TEXT PRIMARY KEY,material_id TEXT REFERENCES materials(id),supplier_id TEXT REFERENCES suppliers(id),quantity REAL NOT NULL,unit_cost REAL NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,item_type TEXT NOT NULL,item_id TEXT NOT NULL,quantity REAL NOT NULL,reason TEXT NOT NULL,reference_id TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(id),quantity REAL NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,operation TEXT NOT NULL,request_id TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS idempotency(request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
    ''')
    if not db.execute('SELECT 1 FROM products').fetchone():
        db.executemany('INSERT INTO customers VALUES(?,?,?)', [('C001','杭州云织服饰','林经理'),('C002','苏州远山家纺','陈经理'),('C003','宁波海风贸易','王经理')])
        db.executemany('INSERT INTO suppliers VALUES(?,?)', [('S001','新源纱业'),('S002','蓝禾染化')])
        db.executemany('INSERT INTO materials VALUES(?,?,?,?,?,?,?)', [('M001','精梳棉纱 32S','kg',3800,1500,26,'S001'),('M002','再生涤纶丝','kg',650,1000,18,'S001'),('M003','活性染料·靛蓝','kg',80,100,48,'S002'),('M004','柔软整理剂','kg',260,150,22,'S002')])
        db.executemany('INSERT INTO products VALUES(?,?,?,?,?,?)', [('P001','云感纯棉府绸','133×72 / 150cm','m',28,1800),('P002','再生涤棉斜纹','108×58 / 150cm','m',32,900),('P003','靛蓝弹力牛仔','10oz / 145cm','m',42,600)])
        db.executemany('INSERT INTO bom VALUES(?,?,?)', [('P001','M001',0.18),('P001','M004',0.008),('P002','M001',0.09),('P002','M002',0.13),('P002','M004',0.01),('P003','M001',0.25),('P003','M003',0.025),('P003','M004',0.012)])
        db.executemany('INSERT INTO machines VALUES(?,?,?,?)', [('MC01','喷气织机 A01','织造一车间','available'),('MC02','喷气织机 A02','织造一车间','available'),('MC03','剑杆织机 B01','织造二车间','available'),('MC04','剑杆织机 B02','织造二车间','maintenance')])
        today = datetime.now(timezone(timedelta(hours=8)))
        for i in range(1,19):
            pid = f'P00{(i-1)%3+1}'
            qty = 800+i*100
            stamp = (today-timedelta(days=(19-i)*5)).isoformat(timespec='seconds')
            due = (today+timedelta(days=i-14)).date().isoformat()
            status = 'shipped' if i<=12 else 'confirmed'
            db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',(f'SO{i:04d}',f'C00{(i-1)%3+1}',pid,qty,[28,32,42][(i-1)%3],due,status,qty if i<=12 else 0,stamp))
            if i<=12:
                wid=f'WO{i:04d}'
                db.execute('INSERT INTO work_orders VALUES(?,?,?,?,?,?,?,?,?)',(wid,f'SO{i:04d}',pid,f'MC0{(i-1)%3+1}',qty+20,qty,20,'completed',stamp))
                db.execute('INSERT INTO production_reports VALUES(?,?,?,?,?,?)',(f'PR{i:04d}',wid,qty,20,'色差' if i%2 else '断经',stamp))
                db.execute('INSERT INTO shipments VALUES(?,?,?,?)',(f'SH{i:04d}',f'SO{i:04d}',qty,stamp))
        db.execute('INSERT INTO work_orders VALUES(?,?,?,?,?,?,?,?,?)',('WO0013','SO0013','P001','MC01',2100,0,0,'planned',now()))
        db.execute("UPDATE orders SET status='in_production' WHERE id='SO0013'")
        for item in rows(db,'SELECT id,stock FROM materials'):
            db.execute('INSERT INTO stock_movements(item_type,item_id,quantity,reason,reference_id,created_at) VALUES(?,?,?,?,?,?)',('material',item['id'],item['stock'],'期初库存','OPENING',now()))
        for item in rows(db,'SELECT id,stock FROM products'):
            db.execute('INSERT INTO stock_movements(item_type,item_id,quantity,reason,reference_id,created_at) VALUES(?,?,?,?,?,?)',('product',item['id'],item['stock'],'期初库存','OPENING',now()))
    db.commit()
    db.close()


def init_agent():
    db=connect('agent')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT REFERENCES sessions(id),role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),status TEXT NOT NULL,error TEXT,usage TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT REFERENCES runs(id),kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,title TEXT NOT NULL,chart_type TEXT NOT NULL,spec TEXT NOT NULL,data TEXT NOT NULL,sql TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS skill_config(id TEXT PRIMARY KEY,body TEXT NOT NULL);
    ''')
    interrupted=rows(db,"SELECT DISTINCT session_id FROM runs WHERE status='running'")
    db.execute("UPDATE runs SET status='interrupted',error='服务重启，执行已中断；请核对工具记录后继续。' WHERE status='running'")
    for session in interrupted:
        history=[json.loads(r['content']) for r in db.execute('SELECT content FROM messages WHERE session_id=? ORDER BY id',(session['session_id'],))]
        answered={m['tool_call_id'] for m in history if m['role']=='tool'}
        for message in history:
            for call in message.get('tool_calls',[]):
                if call['id'] not in answered:
                    body={'role':'tool','tool_call_id':call['id'],'content':'服务重启，工具执行结果未知；必须先查业务审计核对，不能直接重复写入。'}
                    db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(session['session_id'],'tool',json.dumps(body,ensure_ascii=False),now()))
        body={'role':'assistant','content':'上次执行因服务重启中断。已有业务数据已保留，请核对执行记录后继续。'}
        db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)',(session['session_id'],'assistant',json.dumps(body,ensure_ascii=False),now()))
    db.commit()
    db.close()
