"""Reproducible scaling checks in disposable databases, never the user's demo data."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import database, domain, auth


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result={'dataset':{'extra_orders':50000,'audit_rows':30000,'events':100000},'metrics':{}}
    with tempfile.TemporaryDirectory(prefix='textiles-scale-') as folder:
        database.DATA=Path(folder)
        database.init_erp();database.init_agent()
        with database.transaction() as db:
            db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',
                ((f'SCALE{i:06d}',f'C00{i%3+1}','P001',10,28,'2027-01-01','confirmed',0,database.now()) for i in range(50000)))
            db.executemany('INSERT INTO audit(operation,request_id,payload,result,created_at,actor_id) VALUES(?,?,?,?,?,?)',
                (('benchmark',str(i),'x'*512,'y'*512,database.now(),'admin') for i in range(30000)))
        with database.transaction('agent') as db:
            for i in range(100):
                db.execute('INSERT INTO sessions(id,title,created_at,owner_id,access_tag) VALUES(?,?,?,?,?)',(f'S{i}','benchmark',database.now(),'admin','benchmark'))
                db.execute('INSERT INTO runs(id,session_id,status,created_at) VALUES(?,?,?,?)',(f'R{i}',f'S{i}','completed',database.now()))
            db.executemany('INSERT INTO events(run_id,kind,payload,created_at) VALUES(?,?,?,?)',
                ((f'R{i%100}','status',json.dumps({'message':'benchmark'*10}),database.now()) for i in range(100000)))
        credentials=json.loads((database.DATA/'demo-accounts.json').read_text(encoding='utf-8'))[0]
        token=auth.login(credentials['username'],credentials['password'],'benchmark')
        actor=auth.resolve_session(auth.token_digest(token))
        projections=[]
        original=domain.projected_db
        def tracked(*a,**k):
            db=original(*a,**k);projections.append(db.total_changes);return db
        domain.projected_db=tracked
        def measure(label,call):
            samples=[]
            for _ in range(3):
                start=time.perf_counter();value=call();samples.append(round((time.perf_counter()-start)*1000,2))
            result['metrics'][label]={'samples_ms':samples,'median_ms':round(statistics.median(samples),2)}
            return value
        products=measure('small_product_query',lambda:domain.query('SELECT id,name FROM products LIMIT 3',actor))
        assert len(products['rows'])==3
        result['metrics']['small_product_query']['copied_rows_per_request']=projections[-1]
        def poll_events():
            db=database.connect('agent')
            try:return database.rows(db,'SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 201',('R99',0))
            finally:db.close()
        assert len(measure('event_page',poll_events))==201
        db=database.connect('agent')
        try:result['event_query_plan']=[r['detail'] for r in db.execute('EXPLAIN QUERY PLAN SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 201',('R99',0))]
        finally:db.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
