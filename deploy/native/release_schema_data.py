"""Private backup/restore primitives; callers authorize the fixed target first."""
import base64
import hashlib
import json
import math
import os
import re
from pathlib import Path
import socket
import subprocess
import time

from release_core import ReleaseError, canonical, digest
from release_inspect import DB_IDENTITY_SQL, PG_BIN, read_query

CACHE_PATTERNS = ('apikey:auth:*', 'billing:balance:*', 'billing:sub:*', 'sched:*', 'sub2api:dashboard:stats:v1')
MAX_CACHE_BYTES = 64 * 1024 * 1024


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


class Database:
    def __init__(self, env):
        self.env = dict(env)

    def read(self, sql):
        try: return read_query(self.env, sql)
        except Exception: raise ReleaseError('database verification failed; credentials withheld') from None

    def identity(self):
        result = self.read(DB_IDENTITY_SQL)
        return {key: result[key] for key in ('database', 'oid', 'owner', 'system_identifier')}

    def ledger(self):
        return self.read("SELECT coalesce(json_object_agg(filename,checksum),'{}') FROM schema_migrations;")

    def tables(self):
        return self.read("SELECT coalesce(json_agg(json_build_array(n.nspname,c.relname) ORDER BY n.nspname,c.relname),'[]') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%';")

    def counts(self):
        tables = self.tables()
        if len(tables) > 512: raise ReleaseError('database has too many tables for this bounded maintenance')
        return {f'{schema}.{table}': self.read(f'SELECT count(*) FROM {identifier(schema)}.{identifier(table)};') for schema, table in tables}

    def require_idle(self):
        for _ in range(20):
            count = self.read("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend';")
            if count == 0: return
            time.sleep(0.25)
        raise ReleaseError('other database connections remain; no connections were terminated')

    def command(self, program, *args, target=None, timeout=900):
        env = {**self.env, 'PGOPTIONS': '-c lock_timeout=10000 -c statement_timeout=900000'}
        if target is not None: env['PGDATABASE'] = target
        result = subprocess.run([str(PG_BIN / program), *args], env=env, capture_output=True, timeout=timeout)
        if result.returncode: raise ReleaseError(f'{program} failed; database details and credentials withheld')
        return result.stdout

    def dump(self, path):
        # pg_dump creates its file itself; the parent is private, and existing files are rejected.
        if Path(path).exists(): raise ReleaseError('backup dump already exists')
        self.command('pg_dump', '-w', '-Fc', '--file', str(path))
        Path(path).chmod(0o600)
        self.command('pg_restore', '--list', str(path))
        return digest(path)

    def restore(self, path, expected_digest, binding, expected_tables, expected_counts, expected_ledger):
        if self.identity() != binding or self.tables() != expected_tables:
            raise ReleaseError('database target or table set changed; refusing restore')
        if digest(path) != expected_digest: raise ReleaseError('database backup checksum mismatch')
        self.require_idle()
        # Exact 235-237 changes do not add tables. Restore into the SAME database,
        # transactionally; never --create, DROP DATABASE, or a shared-cluster reset.
        self.command('pg_restore', '-w', '--clean', '--if-exists', '--exit-on-error',
                     '--single-transaction', '--dbname', binding['database'], str(path))
        if self.identity() != binding or self.counts() != expected_counts or self.ledger() != expected_ledger:
            raise ReleaseError('restored database did not match the backup checkpoint')

    def rehearsal(self, dump_path, name, migrations):
        # A fresh private clone is used only for data/schema restore verification.
        # Its name is derived from the administrator job ID, never from user input.
        if not re.fullmatch(r'_vsp_restore_[a-f0-9]{32}', name) or name == self.env['PGDATABASE']:
            raise ReleaseError('rehearsal may only create its private job-named database')
        self.command('psql', '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE {identifier(name)} TEMPLATE template0;')
        try:
            self.command('psql', '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-c', f'REVOKE ALL ON DATABASE {identifier(name)} FROM PUBLIC;')
            start = time.monotonic()
            self.command('pg_restore', '-w', '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', '--dbname', name, str(dump_path))
            clone = Database({**self.env, 'PGDATABASE': name})
            if clone.tables() != self.tables() or clone.ledger() != self.ledger():
                raise ReleaseError('rehearsal schema/ledger differs from the running source')
            binding, tables, counts, ledger = clone.identity(), clone.tables(), clone.counts(), clone.ledger()
            for filename in sorted(migrations):
                spec = migrations[filename]
                sql = "BEGIN;\n" + spec['sql'] + "\nINSERT INTO schema_migrations(filename,checksum) VALUES ('" + filename + "','" + spec['ledger_sha256'] + "');\nCOMMIT;"
                clone.command('psql', '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-c', sql)
            clone.restore(dump_path, digest(dump_path), binding, tables, counts, ledger)
            return {'restore_seconds': time.monotonic() - start, 'tables': len(clone.tables())}
        finally:
            self.command('psql', '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-c', f'DROP DATABASE {identifier(name)};')


class RedisCaches:
    """Small bounded RESP client, only used with fixed commands and reviewed prefixes."""
    def __init__(self, values):
        host, port, database = values.get('REDIS_HOST'), values.get('REDIS_PORT'), values.get('REDIS_DB')
        if host not in ('127.0.0.1', 'localhost') or port != '6379' or not str(database).isdigit() or int(database) > 15:
            raise ReleaseError('unexpected Redis target; explicit local configuration is required')
        if values.get('REDIS_ENABLE_TLS', 'false').lower() not in ('false', '0', ''):
            raise ReleaseError('this bounded Redis maintenance does not handle TLS')
        self.host, self.port, self.database = host, int(port), int(database)
        self.password, self.username = values.get('REDIS_PASSWORD', ''), values.get('REDIS_USERNAME', '')

    def call(self, *parts):
        def encode(parts):
            items = [part if isinstance(part, bytes) else str(part).encode() for part in parts]
            return b'*' + str(len(items)).encode() + b'\r\n' + b''.join(b'$' + str(len(item)).encode() + b'\r\n' + item + b'\r\n' for item in items)
        def read(stream, depth=0):
            if depth > 4: raise ReleaseError('Redis response nesting exceeded')
            line = stream.readline(4097)
            if not line.endswith(b'\r\n'): raise ReleaseError('invalid Redis response')
            kind, body = line[:1], line[1:-2]
            if kind == b'-': raise ReleaseError('Redis command failed; details withheld')
            if kind == b'+': return body
            if kind == b':': return int(body)
            if kind == b'$':
                size = int(body)
                if size == -1: return None
                if not 0 <= size <= 4 * 1024 * 1024: raise ReleaseError('Redis value too large')
                result = stream.read(size)
                if len(result) != size or stream.read(2) != b'\r\n': raise ReleaseError('truncated Redis value')
                return result
            if kind == b'*':
                count = int(body)
                if not 0 <= count <= 10000: raise ReleaseError('Redis array too large')
                return [read(stream, depth + 1) for _ in range(count)]
            raise ReleaseError('invalid Redis response type')
        with socket.create_connection((self.host, self.port), timeout=5) as connection, connection.makefile('rb') as stream:
            if self.password:
                connection.sendall(encode(('AUTH', self.username, self.password) if self.username else ('AUTH', self.password))); read(stream)
            connection.sendall(encode(('SELECT', self.database))); read(stream)
            connection.sendall(encode(parts)); return read(stream)

    @staticmethod
    def allowed(key):
        return any(key.startswith(pattern[:-1].encode()) if pattern.endswith('*') else key == pattern.encode() for pattern in CACHE_PATTERNS)

    def keys(self):
        result = set()
        for pattern in CACHE_PATTERNS:
            cursor = b'0'
            while True:
                cursor, keys = self.call('SCAN', cursor, 'MATCH', pattern, 'COUNT', 500)
                if any(not self.allowed(key) for key in keys): raise ReleaseError('unexpected Redis key outside reviewed prefixes')
                result.update(keys)
                if len(result) > 100000: raise ReleaseError('too many application cache keys')
                if cursor == b'0': break
        return sorted(result)

    def snapshot(self, path):
        size = 0
        with Path(path).open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            for key in self.keys():
                ttl = self.call('PTTL', key); value = self.call('DUMP', key)
                if value is None or ttl == -2: continue
                record = {'key': base64.b64encode(key).decode(), 'value': base64.b64encode(value).decode(),
                          'expires': None if ttl == -1 else time.time() + ttl / 1000}
                line = canonical(record) + b'\n'; size += len(line)
                if size > MAX_CACHE_BYTES: raise ReleaseError('application cache snapshot too large')
                stream.write(line)
            stream.flush(); os.fsync(stream.fileno())
        return digest(path)

    def restore(self, path, checksum):
        if digest(path) != checksum: raise ReleaseError('cache backup checksum mismatch')
        if Path(path).stat().st_size > MAX_CACHE_BYTES: raise ReleaseError('cache backup too large')
        # Validate the entire snapshot before deleting any key.
        with Path(path).open('rb') as stream:
            for line in stream:
                record = json.loads(line)
                if not isinstance(record, dict) or set(record) != {'key', 'value', 'expires'}:
                    raise ReleaseError('invalid cache record')
                if not self.allowed(base64.b64decode(record['key'], validate=True)): raise ReleaseError('unapproved cache key')
                value = base64.b64decode(record['value'], validate=True)
                if not value or len(value) > 4 * 1024 * 1024: raise ReleaseError('invalid cache payload')
                expires = record['expires']
                if expires is not None and (type(expires) not in (int, float) or not math.isfinite(expires) or expires < 0):
                    raise ReleaseError('invalid cache expiration')
        for key in self.keys(): self.call('DEL', key)
        with Path(path).open('rb') as stream:
            for line in stream:
                record = json.loads(line)
                ttl = 0 if record['expires'] is None else max(0, int((record['expires'] - time.time()) * 1000))
                if record['expires'] is not None and ttl == 0: continue
                self.call('RESTORE', base64.b64decode(record['key']), ttl, base64.b64decode(record['value']), 'REPLACE')
