import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('DEMO_DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
ERP_PORT = int(os.getenv('ERP_PORT', '8766'))
APP_PORT = int(os.getenv('APP_PORT', '8765'))
ERP_URL = f'http://127.0.0.1:{ERP_PORT}'
INTERNAL_TOKEN = os.getenv('DEMO_INTERNAL_TOKEN', '')
MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')
DEEPSEEK_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')

MAX_AGENT_RUNS = max(1, int(os.getenv("MAX_AGENT_RUNS", "4")))
MAX_USER_RUNS = max(1, int(os.getenv("MAX_USER_RUNS", "2")))
