"""Server-owned role policies and scoped database projections."""
import hashlib
import json
import sqlite3
from fastapi import HTTPException

TABLES = {
    'customers': 'id name contact', 'suppliers': 'id name',
    'materials': 'id name unit stock safety_stock unit_cost supplier_id',
    'products': 'id name spec unit price stock', 'bom': 'product_id material_id quantity',
    'machines': 'id name workshop status',
    'orders': 'id customer_id product_id quantity unit_price due_date status shipped created_at',
    'work_orders': 'id order_id product_id machine_id quantity good_qty bad_qty status created_at',
    'production_reports': 'id work_order_id good_qty bad_qty defect created_at',
    'purchases': 'id material_id supplier_id quantity unit_cost status created_at',
    'stock_movements': 'id item_type item_id quantity reason reference_id created_at',
    'shipments': 'id order_id quantity created_at',
    'audit': 'id operation request_id payload result created_at actor_id',
}
TABLES = {k: v.split() for k, v in TABLES.items()}
OPERATIONS = ['create_order', 'plan_order', 'release_work_order', 'report_production', 'create_purchase', 'receive_purchase', 'ship_order']
COMMAND_TABLES = {
    'create_order':['customers','products','orders'], 'plan_order':['orders','machines','work_orders'],
    'release_work_order':['work_orders','materials','bom'], 'report_production':['work_orders','production_reports','products'],
    'create_purchase':['materials','suppliers','purchases'], 'receive_purchase':['purchases','materials'],
    'ship_order':['orders','products','shipments'],
}


def policy(tables, commands=(), money=False, scope='all'):
    hidden = set() if money else {'price', 'unit_price', 'unit_cost'}
    return {'tables': {t: [c for c in TABLES[t] if c not in hidden] for t in tables.split()},
            'commands': list(commands), 'scope': scope}


DEFAULT_ROLES = {
    'admin': ('系统管理员', policy(' '.join(TABLES), OPERATIONS, True)),
    'manager': ('经营经理', policy(' '.join(t for t in TABLES if t != 'audit'), money=True)),
    'sales': ('销售专员', policy('customers products orders work_orders shipments', ['create_order'], True, 'customers')),
    'production': ('生产主管', policy('products materials bom machines orders work_orders production_reports stock_movements', ['plan_order', 'release_work_order', 'report_production'])),
    'warehouse': ('仓库专员', policy('customers suppliers products materials orders purchases shipments stock_movements', ['receive_purchase', 'ship_order'])),
    'purchasing': ('采购专员', policy('suppliers materials products bom purchases stock_movements', ['create_purchase'], True)),
    'finance': ('财务专员', policy('customers suppliers products materials orders purchases shipments', money=True)),
}
# Procurement needs material costs, but not sales prices.
DEFAULT_ROLES['purchasing'][1]['tables']['products'].remove('price')


def validate_policy(value):
    if set(value) != {'tables', 'commands', 'scope'} or value['scope'] not in ('all', 'customers'):
        raise ValueError('岗位策略格式无效')
    if not isinstance(value['tables'], dict) or not value['tables']:
        raise ValueError('至少授权一个数据表')
    for table, columns in value['tables'].items():
        if table not in TABLES or table == 'audit' or not isinstance(columns, list) or not columns or set(columns) - set(TABLES[table]):
            raise ValueError('数据表或字段授权无效；审计仅限管理员')
    if not isinstance(value['commands'], list) or set(value['commands']) - set(OPERATIONS):
        raise ValueError('业务操作授权无效')
    if value['scope'] == 'customers' and set(value['tables']) - {'customers','products','orders','work_orders','production_reports','shipments','bom'}:
        raise ValueError('客户范围岗位仅支持客户、产品、BOM、订单及相关生产发货数据')
    for command in value['commands']:
        for table in COMMAND_TABLES[command]:
            if table not in value['tables'] or (table != 'bom' and 'id' not in value['tables'][table]):
                raise ValueError(f'业务操作 {command} 需要授权 {table} 及其编号字段')
    return value


def access_tag(user, grants):
    return hashlib.sha256(json.dumps([user['role_id'], user['customer_ids'], grants], sort_keys=True).encode()).hexdigest()


def require_command(actor, operation):
    if operation not in actor['policy']['commands']:
        raise HTTPException(403, '当前岗位不能执行此业务')


def scoped_where(actor, table):
    if actor['policy']['scope'] != 'customers':
        return '', []
    ids = actor['customer_ids']
    placeholders = ','.join('?' for _ in ids) or 'NULL'
    condition = f'customer_id IN ({placeholders})'
    filters = {
        'customers': f'id IN ({placeholders})', 'orders': condition,
        'work_orders': f'order_id IN (SELECT id FROM orders WHERE {condition})',
        'production_reports': f'work_order_id IN (SELECT id FROM work_orders WHERE order_id IN (SELECT id FROM orders WHERE {condition}))',
        'shipments': f'order_id IN (SELECT id FROM orders WHERE {condition})',
    }
    return (' WHERE ' + filters[table], ids) if table in filters else ('', [])


def check_target(db, actor, operation, params):
    require_command(actor, operation)
    if operation == 'create_order' and 'unit_price' in params and 'unit_price' not in actor['policy']['tables'].get('orders', []):
        raise HTTPException(403, '当前岗位不能指定订单价格')
    if actor['policy']['scope'] != 'customers':
        return
    for key, table in [('customer_id','customers'),('order_id','orders'),('work_order_id','work_orders')]:
        if key in params:
            where, args = scoped_where(actor, table)
            if not db.execute(f'SELECT 1 FROM {table}{where} AND id=?', [*args, params[key]]).fetchone():
                raise HTTPException(403, '目标数据不在当前账号负责范围内')


def project_result(actor, result, operation):
    target = {'create_order':'orders','plan_order':'work_orders','release_work_order':'work_orders',
              'report_production':'production_reports','create_purchase':'purchases','receive_purchase':'purchases','ship_order':'shipments'}[operation]
    allowed = actor['policy']['tables'].get(target, [])
    output = {k:v for k,v in result.items() if k in allowed}
    for key, table in [('order','orders'), ('work_order','work_orders')]:
        if isinstance(result.get(key), dict):
            output[key] = {k:v for k,v in result[key].items() if k in actor['policy']['tables'].get(table, [])}
    return output


def command_schema(actor, operation, model):
    schema = model.model_json_schema()
    if operation == 'create_order' and 'unit_price' not in actor['policy']['tables'].get('orders', []):
        schema['properties'].pop('unit_price', None)
    return schema


def projected_db(source, actor):
    """Only authorized rows/columns exist in the SQL execution database."""
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    source.execute('BEGIN')
    try:
        for table, columns in actor['policy']['tables'].items():
            types = {r['name']: r['type'] for r in source.execute(f'PRAGMA table_info({table})')}
            db.execute(f'CREATE TABLE {table} (' + ','.join(f'"{c}" {types[c]}' for c in columns) + ')')
            where, args = scoped_where(actor, table)
            cursor = source.execute('SELECT ' + ','.join(f'"{c}"' for c in columns) + f' FROM {table}' + where, args)
            db.executemany(f'INSERT INTO {table} VALUES (' + ','.join('?' for _ in columns) + ')', cursor)
        db.commit()
        return db
    except BaseException:
        db.close()
        raise
    finally:
        source.rollback()
        source.close()
