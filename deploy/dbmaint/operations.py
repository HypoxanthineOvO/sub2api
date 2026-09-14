"""Typed, bounded maintenance operations. No caller-supplied SQL or credentials."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

READS = {'inspect', 'find-users', 'find-accounts', 'user', 'account', 'usage', 'audit'}
WRITES = {'user-role', 'key-limits', 'key-reset-window'}
USER_COLUMNS = 'id,username,email,role,status,updated_at'
KEY_COLUMNS = 'id,user_id,name,status,quota,quota_used,rate_limit_5h,rate_limit_1d,rate_limit_7d,usage_5h,usage_1d,usage_7d,window_5h_start,window_1d_start,window_7d_start,updated_at'
EXTRA_KEYS = ['session_window_utilization', 'session_window_reset_at'] + [
    f'{p}_{suffix}' for p in ('codex', 'zhipu', 'kimi', 'minimax')
    for suffix in ('5h_used_percent', '5h_reset_at', 'usage_updated_at')]


class MaintenanceError(Exception): pass
class GuardRejected(MaintenanceError): pass


def quote(value):
    return "E'" + value.replace('\\', '\\\\').replace("'", "''") + "'"


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40: raise MaintenanceError('expected an ISO timestamp with timezone')
    try: result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise MaintenanceError('invalid timestamp') from None
    if result.tzinfo is None: raise MaintenanceError('timestamp must include timezone')
    return result


def validate(request):
    if not isinstance(request, dict): raise MaintenanceError('request must be an object')
    op = request.get('operation')
    fields = {
        'inspect': set(), 'find-users': {'search'}, 'find-accounts': {'search'},
        'user': {'id'}, 'account': {'id'}, 'audit': {'id'},
        'usage': {'scope', 'id', 'since', 'until'},
        'user-role': {'id', 'expect_name', 'expect_role', 'role', 'reason'},
        'key-limits': {'id', 'user_id', 'expect_updated_at', 'limits', 'reason'},
        'key-reset-window': {'id', 'user_id', 'window', 'expect_start', 'reason'},
    }
    if not isinstance(op, str) or op not in fields: raise MaintenanceError('operation not authorized')
    if set(request) != fields[op] | {'operation', 'request_id'}: raise MaintenanceError('unexpected or missing request fields')
    if not isinstance(request['request_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', request['request_id']):
        raise MaintenanceError('invalid request identity')
    if op == 'audit':
        if not isinstance(request['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', request['id']): raise MaintenanceError('invalid audit identity')
    else:
        for key in ('id', 'user_id'):
            if key in request and (type(request[key]) is not int or not 0 < request[key] < 2**63): raise MaintenanceError('invalid target ID')
    for key, limit in (('search', 100), ('expect_name', 100), ('reason', 300)):
        if key in request:
            value = request[key]
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise MaintenanceError('invalid text field')
    if op == 'user-role' and (request['role'] not in ('admin', 'user') or request['expect_role'] not in ('admin', 'user')):
        raise MaintenanceError('unsupported role')
    if op == 'usage':
        if request['scope'] not in ('account', 'user', 'key'): raise MaintenanceError('invalid usage scope')
        start, end = timestamp(request['since']), timestamp(request['until'])
        if not 0 < (end - start).total_seconds() <= 7 * 86400: raise MaintenanceError('usage window must be positive and at most seven days')
    if op == 'key-reset-window':
        if request['window'] not in ('5h', '1d', '7d'): raise MaintenanceError('unsupported rate window')
        if request['expect_start'] is not None: timestamp(request['expect_start'])
    if op == 'key-limits':
        timestamp(request['expect_updated_at'])
        values = request['limits']
        if not isinstance(values, dict) or not values or set(values) - {'rate_limit_5h', 'rate_limit_1d', 'rate_limit_7d'}:
            raise MaintenanceError('unsupported limit fields')
        for value in values.values():
            if type(value) not in (str, int, float): raise MaintenanceError('invalid limit')
            try: number = Decimal(str(value))
            except InvalidOperation: raise MaintenanceError('invalid limit') from None
            if not number.is_finite() or not 0 <= number <= 10**9 or number.as_tuple().exponent < -8:
                raise MaintenanceError('limit must be finite, nonnegative and have at most eight decimal places')
    return request


class Operations:
    def __init__(self, database, cache):
        self.database, self.cache = database, cache

    def query(self, sql, write=False):
        if write:
            sql = "BEGIN; SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='20s'; SET LOCAL timezone='UTC'; " + sql + '; COMMIT;'
        result = self.database.command('psql', '-X', '-qAt', '-w', '-v', 'ON_ERROR_STOP=1', '-c', sql,
                                       readonly=not write, timeout=30 if write else 15)
        return json.loads(result)

    def read(self, r):
        op = r['operation']
        if op == 'inspect':
            return {'binding': self.database.identity(), 'server_time': self.query('SELECT to_json(now());'),
                    'operations': sorted(READS | WRITES)}
        if op == 'find-users':
            term = quote(r['search'])
            rows = self.query(f"SELECT coalesce(json_agg(x),'[]') FROM (SELECT {USER_COLUMNS} FROM users WHERE deleted_at IS NULL AND (strpos(username,{term})>0 OR strpos(email,{term})>0 OR strpos(notes,{term})>0) ORDER BY id LIMIT 51) x;")
            return {'matches': rows[:50], 'truncated': len(rows) > 50}
        if op == 'find-accounts':
            term = quote(r['search'])
            rows = self.query(f"SELECT coalesce(json_agg(x),'[]') FROM (SELECT id,name,platform,type,status,session_window_start,session_window_end FROM accounts WHERE deleted_at IS NULL AND (strpos(name,{term})>0 OR strpos(coalesce(notes,''),{term})>0) ORDER BY id LIMIT 51) x;")
            return {'matches': rows[:50], 'truncated': len(rows) > 50}
        if op == 'user':
            user = self.query(f"SELECT (SELECT row_to_json(x) FROM (SELECT {USER_COLUMNS} FROM users WHERE id={r['id']} AND deleted_at IS NULL) x);")
            if user is None: raise MaintenanceError('user not found')
            keys = self.query(f"SELECT coalesce(json_agg(x),'[]') FROM (SELECT {KEY_COLUMNS} FROM api_keys WHERE user_id={r['id']} AND deleted_at IS NULL ORDER BY id LIMIT 201) x;")
            for key in keys:
                fields = self.cache.call('HGETALL', f"apikey:rate:{key['id']}")
                key['live_rate_cache'] = {fields[i].decode(): fields[i+1].decode() for i in range(0, len(fields), 2)
                                          if fields[i] in (b'usage_5h', b'usage_1d', b'usage_7d', b'window_5h', b'window_1d', b'window_7d')}
            return {'user': user, 'keys': keys[:200], 'keys_truncated': len(keys) > 200}
        if op == 'account':
            extra = ','.join(quote(k) + ',extra->' + quote(k) for k in EXTRA_KEYS)
            return self.query(f"SELECT (SELECT row_to_json(x) FROM (SELECT id,name,platform,type,status,session_window_start,session_window_end,updated_at,jsonb_build_object({extra}) AS quota_snapshot FROM accounts WHERE id={r['id']} AND deleted_at IS NULL) x);")
        if op == 'usage':
            column = {'account': 'account_id', 'user': 'user_id', 'key': 'api_key_id'}[r['scope']]
            return self.query(f"""WITH matched AS MATERIALIZED (
                SELECT user_id,api_key_id,model,created_at,input_tokens,output_tokens,actual_cost,ip_address,user_agent
                FROM usage_logs WHERE {column}={r['id']} AND created_at>={quote(r['since'])}::timestamptz
                AND created_at<{quote(r['until'])}::timestamptz
            ), grouped AS (
                SELECT m.user_id,u.username,m.api_key_id,m.ip_address,m.user_agent,count(*) AS requests,
                min(m.created_at) AS first_at,max(m.created_at) AS last_at,
                sum(m.input_tokens) AS input_tokens,sum(m.output_tokens) AS output_tokens,sum(m.actual_cost) AS actual_cost,
                jsonb_agg(DISTINCT m.model) AS models
                FROM matched m LEFT JOIN users u ON u.id=m.user_id
                GROUP BY m.user_id,u.username,m.api_key_id,m.ip_address,m.user_agent
            ) SELECT json_build_object('since',{quote(r['since'])},'until',{quote(r['until'])},
                'time_basis','usage_logs.created_at; end exclusive',
                'requests',(SELECT count(*) FROM matched),'users',(SELECT count(DISTINCT user_id) FROM matched),
                'groups',(SELECT coalesce(json_agg(x),'[]') FROM (SELECT * FROM grouped ORDER BY requests DESC,user_id LIMIT 500) x),
                'truncated',(SELECT count(*)>500 FROM grouped));""")
        raise MaintenanceError('unsupported read operation')

    def mutate(self, r):
        op = r['operation']
        if op == 'user-role':
            role, old = quote(r['role']), quote(r['expect_role'])
            # Serialize this tool's role edits and avoid demoting the last active admin.
            sql = f"""LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE;
                WITH before AS MATERIALIZED (SELECT {USER_COLUMNS} FROM users WHERE id={r['id']}
                    AND username={quote(r['expect_name'])} AND role={old} AND deleted_at IS NULL FOR UPDATE),
                changed AS (UPDATE users SET role={role},updated_at=now() WHERE id IN (SELECT id FROM before)
                    AND ({role}='admin' OR {old}<>'admin' OR (SELECT count(*) FROM users WHERE role='admin' AND status='active' AND deleted_at IS NULL)>1)
                    RETURNING {USER_COLUMNS})
                SELECT json_build_object('before',(SELECT row_to_json(b) FROM before b),'after',(SELECT row_to_json(c) FROM changed c))"""
        else:
            if op == 'key-limits':
                assignments = ','.join(f'{k}={Decimal(str(v))}' for k, v in r['limits'].items())
                guard = f"updated_at={quote(r['expect_updated_at'])}::timestamptz"
            elif op == 'key-reset-window':
                window = r['window']
                expected = 'NULL' if r['expect_start'] is None else quote(r['expect_start']) + '::timestamptz'
                assignments = f'usage_{window}=0,window_{window}_start=NULL'
                guard = f'window_{window}_start IS NOT DISTINCT FROM {expected}'
            else: raise MaintenanceError('unsupported write operation')
            sql = f"""WITH before AS MATERIALIZED (SELECT {KEY_COLUMNS} FROM api_keys WHERE id={r['id']}
                AND user_id={r['user_id']} AND deleted_at IS NULL AND {guard} FOR UPDATE),
                changed AS (UPDATE api_keys SET {assignments},updated_at=now() WHERE id IN (SELECT id FROM before) RETURNING {KEY_COLUMNS})
                SELECT json_build_object('before',(SELECT row_to_json(b) FROM before b),'after',(SELECT row_to_json(c) FROM changed c))"""
        result = self.query(sql, write=True)
        if not result['after']: raise GuardRejected('target changed, owner mismatch, or last-admin guard rejected the write; no row changed')
        return result

    def invalidate(self, r):
        predicate = f"user_id={r['id']}" if r['operation'] == 'user-role' else f"id={r['id']} AND user_id={r['user_id']}"
        # These credentials stay inside the root process; only SHA-256 cache IDs
        # go to Redis, and neither credential nor cache IDs enter results/audits.
        keys = self.query(f"SELECT coalesce(json_agg(key),'[]') FROM api_keys WHERE {predicate} AND deleted_at IS NULL;")
        for key in keys:
            hashed = hashlib.sha256(key.encode()).hexdigest()
            self.cache.call('DEL', 'apikey:auth:' + hashed)
            self.cache.call('PUBLISH', 'auth:cache:invalidate', hashed)
        if r['operation'] == 'key-reset-window': self.cache.call('DEL', f"apikey:rate:{r['id']}")
        return len(keys)


def perform(request, operations, read_record, save_record):
    """Never replay a database write after an ambiguous commit or cache failure."""
    r = validate(request)
    previous = read_record(r['request_id'])
    if previous:
        if previous['request'] != r: raise MaintenanceError('request ID was already used for different parameters')
        if previous['phase'] == 'complete': return previous
        if previous['phase'] == 'cache_pending':
            operations.invalidate(r)
            previous['phase'] = 'complete'; save_record(r['request_id'], previous); return previous
        raise MaintenanceError('prior attempt has an unresolved or rejected outcome; inspect its audit record before a new write')
    record = {'request': r, 'phase': 'intent', 'actor': 'ssh:heyx', 'created_at': datetime.now(timezone.utc).isoformat()}
    save_record(r['request_id'], record)
    try:
        if r['operation'] in WRITES:
            operations.cache.call('PING')
            record['result'] = operations.mutate(r)
            record['phase'] = 'cache_pending'; save_record(r['request_id'], record)
            operations.invalidate(r)
        else:
            record['result'] = read_record(r['id']) if r['operation'] == 'audit' else operations.read(r)
        record['phase'] = 'complete'
        save_record(r['request_id'], record)
        return record
    except GuardRejected as error:
        record.update(phase='rejected', error=str(error)); save_record(r['request_id'], record); raise
    except Exception:
        # intent may mean an interrupted COMMIT; cache_pending means DB committed.
        # Keep that distinction durable and never guess that nothing happened.
        raise MaintenanceError(f"maintenance did not finish; inspect audit {r['request_id']} (phase {record['phase']}); details withheld") from None
