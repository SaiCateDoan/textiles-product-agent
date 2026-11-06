"""Local password authentication, revocable sessions, and fresh role resolution."""
import hashlib
import hmac
import json
import re
import secrets
import time
from contextvars import ContextVar
from fastapi import HTTPException
from . import database
from .permissions import DEFAULT_ROLES, TABLES, OPERATIONS, validate_policy, access_tag

session_context = ContextVar('actor_session', default='')
COOKIE = 'demo_session'
TTL = 8 * 3600


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def init_auth():
    with database.transaction('agent') as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS roles(id TEXT PRIMARY KEY,name TEXT NOT NULL,policy TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password_hash TEXT NOT NULL,role_id TEXT NOT NULL REFERENCES roles(id),customer_ids TEXT NOT NULL DEFAULT '[]',active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts(username TEXT NOT NULL,ip TEXT NOT NULL,created REAL NOT NULL);
        ''')
        for key, (name, policy) in DEFAULT_ROLES.items():
            db.execute('INSERT OR IGNORE INTO roles VALUES(?,?,?)', (key, name, json.dumps(policy)))
        credentials = []
        if not db.execute('SELECT 1 FROM users').fetchone():
            for role, (name, _) in DEFAULT_ROLES.items():
                password = secrets.token_urlsafe(12)
                customers = ['C001'] if role == 'sales' else []
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,1)', (role, role, name, password_hash(password), role, json.dumps(customers)))
                credentials.append({'username': role, 'password': password, 'role': name})
        for table in ('sessions','reports'):
            columns = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            for column in ('owner_id','access_tag'):
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            admin = db.execute("SELECT * FROM users WHERE id='admin'").fetchone()
            if admin:
                grants = json.loads(db.execute("SELECT policy FROM roles WHERE id='admin'").fetchone()[0])
                user = dict(admin); user['customer_ids'] = json.loads(user['customer_ids'])
                db.execute(f"UPDATE {table} SET owner_id='admin',access_tag=? WHERE owner_id=''", (access_tag(user, grants),))
    if credentials:
        path = database.DATA / 'demo-accounts.json'
        path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding='utf-8')


def resolve_session(token_hash):
    db = database.connect('agent')
    try:
        row = db.execute('''SELECT u.*,s.csrf,s.expires,r.name role_name,r.policy FROM auth_sessions s
            JOIN users u ON u.id=s.user_id JOIN roles r ON r.id=u.role_id
            WHERE s.token_hash=? AND u.active=1 AND s.expires>?''', (token_hash, time.time())).fetchone()
        if not row:
            raise HTTPException(401, '请登录后使用系统')
        actor = dict(row)
        actor.pop('password_hash')
        actor['customer_ids'] = json.loads(actor['customer_ids'])
        actor['policy'] = json.loads(actor['policy'])
        actor['access_tag'] = access_tag(actor, actor['policy'])
        actor['session_hash'] = token_hash
        return actor
    finally:
        db.close()


def current_actor():
    return resolve_session(session_context.get())


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(username, password, ip):
    username = username.strip().lower()
    timestamp = time.time()
    denied = False
    with database.transaction('agent') as db:
        db.execute('DELETE FROM login_attempts WHERE created<?', (timestamp-300,))
        count = db.execute('SELECT COUNT(*) FROM login_attempts WHERE username=? OR ip=?', (username, ip)).fetchone()[0]
        if count >= 10:
            raise HTTPException(429, '尝试次数过多，请5分钟后重试')
        user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        stored = user['password_hash'] if user else password_hash('dummy-account')
        valid = hmac.compare_digest(stored, password_hash(password, stored.split(':')[0]))
        if not user or not valid or not user['active']:
            db.execute('INSERT INTO login_attempts VALUES(?,?,?)', (username, ip, timestamp))
            denied = True
        else:
            db.execute('DELETE FROM login_attempts WHERE username=?', (username,))
            db.execute('DELETE FROM auth_sessions WHERE expires<?', (timestamp,))
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO auth_sessions VALUES(?,?,?,?)', (token_digest(token), user['id'], secrets.token_urlsafe(32), timestamp+TTL))
    if denied:
        raise HTTPException(401, '账号或密码错误，或账号已停用')
    return token


def require_admin():
    actor = current_actor()
    if actor['role_id'] != 'admin':
        raise HTTPException(403, '仅系统管理员可执行此操作')
    return actor


def public_actor(actor):
    return {k:actor[k] for k in ('id','username','name','role_id','role_name','customer_ids','policy')}


def artifact_owner():
    actor = current_actor()
    return actor['id'], actor['access_tag']


def ensure_session(db, identity):
    owner, tag = artifact_owner()
    if not db.execute('SELECT 1 FROM sessions WHERE id=? AND owner_id=? AND access_tag=?', (identity,owner,tag)).fetchone():
        raise HTTPException(404, '会话不存在')


def admin_data():
    require_admin()
    db = database.connect('agent')
    try:
        users = database.rows(db, 'SELECT id,username,name,role_id,customer_ids,active FROM users ORDER BY username')
        roles = database.rows(db, 'SELECT * FROM roles ORDER BY id')
        for user in users: user['customer_ids'] = json.loads(user['customer_ids'])
        for role in roles: role['policy'] = json.loads(role['policy'])
        return {'users':users, 'roles':roles, 'tables':TABLES, 'commands':OPERATIONS}
    finally:
        db.close()


def save_user(identity, body):
    require_admin()
    username = str(body.get('username','')).strip().lower()
    name = str(body.get('name','')).strip()
    password = body.get('password','')
    scope = body.get('customer_ids',[])
    role = body.get('role_id','')
    active = body.get('active', True)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{2,39}', username) or not 1 <= len(name) <= 80:
        raise ValueError('账号使用3至40位英文小写字母、数字、下划线；姓名不能为空')
    if not isinstance(active, bool) or not isinstance(scope, list) or len(scope)>100 or any(not isinstance(x,str) or len(x)>80 for x in scope):
        raise ValueError('账号范围或启用状态无效')
    if password and (not isinstance(password,str) or not 10 <= len(password) <= 128):
        raise ValueError('密码需要10至128个字符')
    with database.transaction('agent') as db:
        existing = db.execute('SELECT * FROM users WHERE id=?',(identity,)).fetchone()
        if not db.execute('SELECT 1 FROM roles WHERE id=?',(role,)).fetchone():
            raise ValueError('岗位不存在')
        if existing and existing['role_id']=='admin' and (role!='admin' or not active):
            if db.execute("SELECT COUNT(*) FROM users WHERE role_id='admin' AND active=1 AND id!=?",(identity,)).fetchone()[0]==0:
                raise ValueError('必须保留至少一个启用的管理员')
        if not existing and not password:
            raise ValueError('新账号必须设置密码')
        hashed = password_hash(password) if password else existing['password_hash']
        try:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,name=excluded.name,password_hash=excluded.password_hash,role_id=excluded.role_id,customer_ids=excluded.customer_ids,active=excluded.active',
                       (identity,username,name,hashed,role,json.dumps(scope),int(active)))
        except database.sqlite3.IntegrityError:
            raise ValueError('账号已存在')
        db.execute('DELETE FROM auth_sessions WHERE user_id=?',(identity,))
    return {'status':'saved'}


def save_role(identity, body):
    require_admin()
    if identity == 'admin' or identity not in DEFAULT_ROLES:
        raise ValueError('管理员岗位不可修改；请选择已存在岗位')
    policy = validate_policy(body['policy'])
    name = str(body.get('name','')).strip()
    if not 1 <= len(name) <= 80: raise ValueError('岗位名称无效')
    with database.transaction('agent') as db:
        db.execute('UPDATE roles SET name=?,policy=? WHERE id=?',(name,json.dumps(policy),identity))
        db.execute('DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM users WHERE role_id=?)',(identity,))
    return {'status':'saved'}
