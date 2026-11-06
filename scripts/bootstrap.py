"""Dependency bootstrap using the Python standard library, no Node/Docker required."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

root=Path(__file__).resolve().parent.parent
if sys.version_info<(3,11):
    raise SystemExit('Python 3.11+ is required.')
venv_dir=root/'.venv'
python=venv_dir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if not python.exists():
    venv.EnvBuilder(with_pip=True).create(venv_dir)
digest=hashlib.sha256((root/'requirements.txt').read_bytes()).hexdigest()
marker=venv_dir/'requirements.sha256'
if not marker.exists() or marker.read_text()!=digest:
    uv=shutil.which('uv')
    if uv:
        command=[uv,'pip','install','--python',str(python),'-r',str(root/'requirements.txt')]
    else:
        subprocess.run([str(python),'-m','ensurepip','--upgrade'],check=True)
        command=[str(python),'-m','pip','install','-r',str(root/'requirements.txt')]
    subprocess.run(command,check=True,cwd=root)
    marker.write_text(digest)
print('Dependencies ready.')
