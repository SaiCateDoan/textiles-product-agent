"""Measure live role workspaces without modifying business data or exposing credentials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--accounts',type=Path,default=ROOT/'data'/'demo-accounts.json')
    parser.add_argument('--samples',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.samples<=100:parser.error('--samples must be between 1 and 100')
    accounts={a['username']:a for a in json.loads(args.accounts.read_text(encoding='utf-8'))}
    evidence={'recorded_at':datetime.now(timezone.utc).isoformat(),'platform':platform.system(),
              'samples_per_metric':args.samples,'roles':{}}
    with httpx.Client(base_url=args.base_url,trust_env=False,timeout=40) as client:
        for role in ('admin','sales','production'):
            account=accounts[role]
            client.post('/api/auth/login',headers={'X-Demo-Login':'1'},json={k:account[k] for k in ('username','password')}).raise_for_status()
            try:
                bootstrap=client.get('/api/bootstrap');bootstrap.raise_for_status()
                client.headers['X-Demo-Token']=bootstrap.json()['token']
                metrics={}
                for label,method,path,body in [('http_query','POST','/api/query',{'sql':'SELECT COUNT(*) n FROM orders'}),('dashboard','GET','/api/dashboard',None)]:
                    samples=[]
                    for _ in range(args.samples):
                        started=time.perf_counter()
                        response=client.request(method,path,json=body)
                        elapsed=(time.perf_counter()-started)*1000
                        response.raise_for_status()
                        samples.append(round(elapsed,2))
                    metrics[label]={'samples_ms':samples,'median_ms':round(statistics.median(samples),2)}
                evidence['roles'][role]=metrics
                print(role+' '+json.dumps(metrics),flush=True)
            finally:
                client.post('/api/auth/logout').raise_for_status()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
