"""Real Windows launcher regressions; isolated ports/data, no model API calls."""
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows one-click launcher')


def free_ports():
    with socket.socket() as app, socket.socket() as erp:
        app.bind(('127.0.0.1',0))
        erp.bind(('127.0.0.1',0))
        return app.getsockname()[1],erp.getsockname()[1]


@pytest.fixture
def demo(tmp_path):
    app_port,erp_port=free_ports()
    runtime=tmp_path/'runtime'
    data=tmp_path/'data'
    env=os.environ.copy()
    env.update(APP_PORT=str(app_port),ERP_PORT=str(erp_port),DEMO_RUNTIME_DIR=str(runtime),DEMO_DATA_DIR=str(data))
    processes=[]
    logs=[]
    client=httpx.Client(base_url=f'http://127.0.0.1:{app_port}',timeout=5,trust_env=False)

    def start():
        path=tmp_path/f'start-{len(processes)}.log'
        log=path.open('wb')
        logs.append(log)
        p=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'start.ps1'),'-NoBrowser'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(p)
        return p,path

    def wait(started):
        process,path=started
        process.wait(timeout=50)
        return process.returncode,path.read_text(encoding='utf-8',errors='replace')

    def stop():
        bootstrap=client.get('/api/bootstrap').json()
        response=client.post('/api/shutdown',headers={'X-Demo-Token':bootstrap['token']})
        response.raise_for_status()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if not (runtime/'state.json').exists():
                for port in (app_port,erp_port):
                    with socket.socket() as sock:
                        assert sock.connect_ex(('127.0.0.1',port))!=0
                return
            time.sleep(.1)
        pytest.fail('Demo did not close both services')

    yield {'start':start,'wait':wait,'stop':stop,'client':client,'runtime':runtime,'data':data,'port':app_port,'env':env}
    try:
        if (runtime/'state.json').exists():
            (runtime/'shutdown.request').write_text('test-cleanup')
            deadline=time.monotonic()+15
            while (runtime/'state.json').exists() and time.monotonic()<deadline:
                time.sleep(.1)
        for p in processes:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=5)
    finally:
        client.close()
        for log in logs:
            log.close()


def test_concurrent_launch_reuse_and_restart(demo):
    starts=[demo['start'](),demo['start']()]
    for started in starts:
        code,output=demo['wait'](started)
        assert code==0,output
        assert 'Demo ready:' in output
    first=demo['client'].get('/api/health').json()['instance_id']
    assert first
    code,output=demo['wait'](demo['start']())
    assert code==0,output
    assert demo['client'].get('/api/health').json()['instance_id']==first
    assert len(list(demo['runtime'].glob('launcher-*.out.log')))>=1
    assert (demo['runtime']/'launcher.lock').stat().st_size==1
    demo['stop']()
    code,output=demo['wait'](demo['start']())
    assert code==0,output
    assert demo['client'].get('/api/health').json()['instance_id']!=first
    demo['stop']()


def test_occupied_port_reports_actual_cause(demo):
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',demo['port']))
        occupied.listen()
        code,output=demo['wait'](demo['start']())
        assert code!=0
        assert f"Port {demo['port']} is busy" in output
        assert 'Startup log:' in output
        assert not (demo['runtime']/'state.json').exists()


def test_child_failure_reports_current_log(demo):
    demo['data'].mkdir()
    (demo['data']/'erp.sqlite3').write_bytes(b'not a SQLite database')
    code,output=demo['wait'](demo['start']())
    assert code!=0
    assert 'erp service exited' in output
    assert 'file is not a database' in output
    assert not (demo['runtime']/'state.json').exists()
