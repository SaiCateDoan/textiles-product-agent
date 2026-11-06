"""Own exactly two child services; a browser shutdown ends both and this supervisor."""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from .config import ROOT,APP_PORT,ERP_PORT


def main():
    runtime=Path(os.getenv('DEMO_RUNTIME_DIR',str(ROOT/'.runtime')))
    runtime.mkdir(parents=True,exist_ok=True)
    launch_id=os.getenv('DEMO_LAUNCH_ID') or secrets.token_hex(16)
    lock=(runtime/'launcher.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if lock.seek(0,os.SEEK_END)==0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        print('Demo supervisor is already running.',flush=True)
        return
    if APP_PORT==ERP_PORT:
        raise RuntimeError('APP_PORT and ERP_PORT must be different.')
    for port in (APP_PORT,ERP_PORT):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1',port))
            except OSError:
                raise RuntimeError(f'Port {port} is busy. Stop the existing service or change APP_PORT/ERP_PORT.')
    shutdown=runtime/'shutdown.request'
    shutdown.unlink(missing_ok=True)
    env=os.environ.copy()
    env['DEMO_INTERNAL_TOKEN']=secrets.token_urlsafe(40)
    env['DEMO_LAUNCH_ID']=launch_id
    env['DEMO_SHUTDOWN_FILE']=str(shutdown)
    env['PYTHONUNBUFFERED']='1'
    children=[]
    logs=[]
    stopping=False
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGTERM,stop)
    try:
        for module,port,name in [('app.erp',ERP_PORT,'erp'),('app.server',APP_PORT,'agent')]:
            log=(runtime/f'{name}.log').open('wb')
            logs.append(log)
            child=subprocess.Popen([sys.executable,'-m','uvicorn',module+':app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append(child)
        state={'supervisor_pid':os.getpid(),'children':[p.pid for p in children],'app_port':APP_PORT,'erp_port':ERP_PORT,'workspace':str(ROOT),'launch_id':launch_id}
        state_temp=runtime/f'state-{launch_id}.tmp'
        state_temp.write_text(json.dumps(state),encoding='utf-8')
        state_temp.replace(runtime/'state.json')
        print(f'Demo listening at http://127.0.0.1:{APP_PORT}',flush=True)
        while not stopping and not shutdown.exists():
            for child,name in zip(children,('erp','agent')):
                if child.poll() is not None:
                    log_path=runtime/f'{name}.log'
                    tail='\n'.join(log_path.read_text(encoding='utf-8',errors='replace').splitlines()[-30:])
                    raise RuntimeError(f'{name} service exited (exit {child.returncode}). Log: {log_path}\n{tail}')
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for log in logs:
            log.close()
        (runtime/'state.json').unlink(missing_ok=True)
        shutdown.unlink(missing_ok=True)
        lock.close()


if __name__=='__main__':
    main()
