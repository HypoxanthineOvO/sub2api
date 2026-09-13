#!/usr/bin/env python3
"""Babel-only administrator READ-ONLY preflight. Never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

BABEL = 'iZuf668tiyo0blc17ihbtyZ'
PG_BIN = Path('/usr/lib/postgresql/16/bin')
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')
UNITS = ('vsp-sub2api-app-slot@blue.service', 'vsp-sub2api-app-slot@green.service',
         'vsp-postgresql@production.service', 'vsp-redis@production.service',
         'vsp-mihomo-production@general.service', 'nginx.service', 'cloudflared.service')


def unit_info(name):
    result = subprocess.run(['/usr/bin/systemctl', 'show', name, '-p', 'MainPID,ActiveState,DropInPaths'],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError('service inspection failed')
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def runtime_environment(pid):
    if not str(pid).isdigit() or int(pid) <= 0:
        raise ValueError('a running application is required')
    data = Path(f'/proc/{int(pid)}/environ').read_bytes()
    return {key.decode(): value.decode() for item in data.split(b'\0') if b'=' in item
            for key, value in [item.split(b'=', 1)] if key.startswith((b'DATABASE_', b'REDIS_'))}


def database_environment(values):
    names = {'PGHOST': 'DATABASE_HOST', 'PGPORT': 'DATABASE_PORT', 'PGUSER': 'DATABASE_USER',
             'PGDATABASE': 'DATABASE_DBNAME', 'PGPASSWORD': 'DATABASE_PASSWORD'}
    if any(name not in values for name in names.values()):
        raise ValueError('explicit database configuration is required')
    env = {key: values[name] for key, name in names.items()}
    if env['PGHOST'] not in ('127.0.0.1', 'localhost') or env['PGPORT'] != '5432':
        raise ValueError('unexpected database endpoint')
    if not IDENTIFIER.fullmatch(env['PGUSER']) or not IDENTIFIER.fullmatch(env['PGDATABASE']):
        raise ValueError('unsupported database identifier')
    env.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin', PGCONNECT_TIMEOUT='5',
               PGSSLMODE=values.get('DATABASE_SSLMODE', 'disable'))
    return env


def read_query(env, sql):
    safe = {**env, 'PGOPTIONS': '-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=1000'}
    result = subprocess.run([str(PG_BIN / 'psql'), '-X', '-w', '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql],
                            env=safe, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('read-only database query failed (details withheld)')
    return json.loads(result.stdout)


DB_IDENTITY_SQL = """SELECT json_build_object('database',current_database(),'oid',d.oid,
 'owner',pg_get_userbyid(d.datdba),'bytes',pg_database_size(d.oid),
 'server_version',current_setting('server_version'),'system_identifier',CASE WHEN r.rolsuper THEN (SELECT system_identifier::text FROM pg_control_system()) ELSE NULL END,
 'role',current_user,'superuser',r.rolsuper,'createdb',r.rolcreatedb)
 FROM pg_database d JOIN pg_roles r ON r.rolname=current_user
 WHERE d.datname=current_database();"""

QUERIES = {
    'database': DB_IDENTITY_SQL,
    'migrations': "SELECT json_build_object('count',count(*),'last',max(filename),'pending_target_present',count(*) FILTER(WHERE filename IN ('235_group_model_allowlist.sql','236_group_model_allowlist_repair.sql','237_add_minimax_platform.sql'))) FROM schema_migrations;",
    'group_columns': "SELECT coalesce(json_agg(column_name),'[]') FROM information_schema.columns WHERE table_schema='public' AND table_name='groups' AND column_name IN ('models_list_config','model_allowlist');",
    'model_lists': "SELECT json_build_object('active_groups',count(*),'enabled_lists',count(*) FILTER(WHERE models_list_config->>'enabled'='true')) FROM groups WHERE deleted_at IS NULL;",
    'retained_platforms': "SELECT json_build_object('quota_rows',(SELECT count(*) FROM user_platform_quotas WHERE platform IN ('mimo','hunyuan','qwen')),'route_rows',(SELECT count(*) FROM composite_model_routes WHERE target_platform IN ('mimo','hunyuan','qwen')));",
    'deepseek_pricing': "SELECT json_build_object('rows',count(*),'time_pricing_rows',count(*) FILTER(WHERE time_pricing IS NOT NULL AND time_pricing <> '{}'::jsonb),'weekdays_only_rows',count(*) FILTER(WHERE time_pricing->>'weekdays_only'='true')) FROM channel_model_pricing WHERE platform='deepseek';",
    'connections': "SELECT coalesce(json_agg(row_to_json(x)),'[]') FROM (SELECT usename,state,count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend' GROUP BY usename,state) x;",
    'pending_batches': "SELECT count(*) FROM batch_image_jobs WHERE status NOT IN ('completed','failed','cancelled','output_deleted');",
}


def inspect():
    services = {name: unit_info(name) for name in UNITS}
    active = [record for name, record in services.items() if 'app-slot@' in name and record.get('ActiveState') == 'active']
    if not active:
        raise ValueError('no running application to inspect')
    values = runtime_environment(active[0]['MainPID'])
    env = database_environment(values)
    report = {'mode': 'read-only', 'hostname': socket.gethostname(), 'services': services}
    for name, query in QUERIES.items():
        try: report[name] = read_query(env, query)
        except ValueError: report[name] = {'error': 'READ_ONLY_QUERY_FAILED'}
    report['redis'] = {name: values.get('REDIS_' + name.upper(), '') for name in ('host', 'port', 'db')}
    report['libexec_parent_exists'] = Path('/usr/local/libexec').exists()
    report['filesystem'] = {'free_bytes': shutil.disk_usage('/var/lib').free}
    for name in ('/var/lib/vsp-sub2api/production', '/var/lib/vsp-sub2api/production/app', '/etc/vsp-sub2api/production/app.env'):
        st = Path(name).lstat()
        report['filesystem'][name] = {'mode': oct(st.st_mode & 0o7777), 'uid': st.st_uid, 'gid': st.st_gid}
    report['available_memory_kib'] = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != BABEL:
        parser.error('run this read-only inspection as administrator on Babel')
    try:
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
    except Exception as error:
        raise SystemExit(f'read-only preflight failed ({type(error).__name__}); no changes made, credentials withheld')
