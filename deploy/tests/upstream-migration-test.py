#!/usr/bin/env python3
"""Rehearse 235-237 on an isolated PostgreSQL cluster, never an existing DB.

Requires local PostgreSQL server tools (PG_BINDIR can select their directory).
The temporary cluster exposes only a private Unix socket, no TCP listener.
This tests migration SQL and fixture backup restoration, not a live cutover.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

MIGRATIONS = Path(__file__).resolve().parents[2] / 'backend' / 'migrations'


class UpstreamMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid() == 0:
            raise unittest.SkipTest('run as a non-root developer')
        bindir = os.environ.get('PG_BINDIR')
        if not bindir:
            pg_config = shutil.which('pg_config')
            if not pg_config:
                raise unittest.SkipTest('PostgreSQL server tools are required')
            bindir = subprocess.check_output([pg_config, '--bindir'], text=True).strip()
        cls.bindir = Path(bindir)
        for tool in ('initdb', 'pg_ctl', 'psql', 'pg_dump', 'pg_restore'):
            if not (cls.bindir / tool).is_file():
                raise unittest.SkipTest(f'missing PostgreSQL tool: {tool}')
        cls.temp = tempfile.TemporaryDirectory(prefix='vsp-migrations-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / 'data'
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
        cls.env.update(PGHOST=str(cls.root), PGPORT='5432', PGUSER='vsp_test', PGDATABASE='postgres')
        cls.command('initdb', '-D', str(cls.data), '-U', 'vsp_test',
                    '--auth-local=trust', '--auth-host=reject', '--no-locale', '--encoding=UTF8')
        cls.addClassCleanup(cls.stop)
        cls.command('pg_ctl', '-D', str(cls.data), '-l', str(cls.root / 'postgres.log'),
                    '-o', f"-F -k {cls.root} -c listen_addresses='' -c max_connections=10 -c shared_buffers=16MB",
                    '-w', 'start', env={**cls.env, 'PGHOST': str(cls.root)})

    @classmethod
    def command(cls, tool, *args, input=None, check=True, env=None):
        result = subprocess.run([str(cls.bindir / tool), *args], input=input,
                                capture_output=True, env=env or cls.env, timeout=45)
        if check and result.returncode:
            raise AssertionError(result.stderr.decode(errors='replace'))
        return result

    @classmethod
    def stop(cls):
        if (cls.data / 'postmaster.pid').exists():
            cls.command('pg_ctl', '-D', str(cls.data), '-m', 'fast', '-w', 'stop')

    def setUp(self):
        self.sql('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')

    def sql(self, sql, check=True, database='postgres'):
        return self.command('psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', database,
                            input=sql.encode(), check=check)

    def migration(self, name):
        self.sql((MIGRATIONS / name).read_text())

    def platform_fixture(self):
        self.sql('''
            CREATE TABLE user_platform_quotas (platform TEXT NOT NULL);
            CREATE TABLE composite_model_routes (target_platform TEXT NOT NULL);
            CREATE TABLE channel_monitors (provider TEXT NOT NULL);
            CREATE TABLE channel_monitor_request_templates (provider TEXT NOT NULL);
        ''')
        self.migration('231_add_minimax_mimo_providers.sql')
        self.migration('232_add_hunyuan_qwen_providers.sql')
        self.sql('''
            INSERT INTO user_platform_quotas VALUES ('minimax'), ('mimo'), ('hunyuan'), ('qwen');
            INSERT INTO composite_model_routes VALUES ('minimax'), ('mimo'), ('hunyuan'), ('qwen');
            INSERT INTO channel_monitors VALUES ('minimax'), ('mimo');
            INSERT INTO channel_monitor_request_templates VALUES ('minimax'), ('mimo');
        ''')

    def test_platform_superset_survives_upgrade_and_replay(self):
        self.platform_fixture()
        for _ in range(2):
            self.migration('237_add_minimax_platform.sql')
        for table, column, expected in [
            ('user_platform_quotas', 'platform', 'hunyuan,mimo,minimax,qwen'),
            ('composite_model_routes', 'target_platform', 'hunyuan,mimo,minimax,qwen'),
            ('channel_monitors', 'provider', 'mimo,minimax'),
            ('channel_monitor_request_templates', 'provider', 'mimo,minimax'),
        ]:
            with self.subTest(table=table):
                actual = self.sql(f"SELECT string_agg({column}, ',' ORDER BY {column}) FROM {table};")
                self.assertEqual(actual.stdout.decode().strip(), expected)
                self.assertNotEqual(self.sql(f"INSERT INTO {table} VALUES ('unknown');", check=False).returncode, 0)

    def test_narrowed_constraint_would_reject_retained_rows(self):
        self.platform_fixture()
        result = self.sql('''BEGIN;
            ALTER TABLE user_platform_quotas DROP CONSTRAINT user_platform_quotas_platform_check;
            ALTER TABLE user_platform_quotas ADD CONSTRAINT user_platform_quotas_platform_check
                CHECK (platform IN ('anthropic','openai','gemini','antigravity','grok','kimi','zhipu','deepseek','minimax'));
            COMMIT;''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('check constraint', result.stderr.decode())
        self.migration('237_add_minimax_platform.sql')

    def test_column_rename_requires_database_restore_for_old_reader(self):
        self.sql('''CREATE TABLE groups (models_list_config JSONB NOT NULL DEFAULT '{}');
            INSERT INTO groups VALUES ('{"enabled":true,"models":["example-model"]}');''')
        dump = self.command('pg_dump', '-Fc', '-d', 'postgres').stdout
        for _ in range(2):
            self.migration('235_group_model_allowlist.sql')
            self.migration('236_group_model_allowlist_repair.sql')
        self.assertEqual(self.sql("SELECT model_allowlist->'models'->>0 FROM groups;").stdout.strip(), b'example-model')
        self.assertNotEqual(self.sql('SELECT models_list_config FROM groups;', check=False).returncode, 0)
        self.sql('CREATE DATABASE restored;')
        try:
            self.command('pg_restore', '--exit-on-error', '-d', 'restored', input=dump)
            self.assertEqual(self.sql("SELECT models_list_config->'models'->>0 FROM groups;", database='restored').stdout.strip(), b'example-model')
        finally:
            self.sql('DROP DATABASE restored;')

    def test_repair_preserves_new_values_and_backfills_only_empty_values(self):
        self.sql('''CREATE TABLE groups (models_list_config JSONB, model_allowlist JSONB);
            INSERT INTO groups VALUES ('{"models":["old"]}', '{}'),
                                      ('{"models":["old"]}', '{"models":["new"]}');''')
        for _ in range(2):
            self.migration('236_group_model_allowlist_repair.sql')
        self.assertEqual(self.sql("SELECT model_allowlist->'models'->>0 FROM groups ORDER BY 1;").stdout.strip(), b'new\nold')
        self.assertNotEqual(self.sql('INSERT INTO groups (model_allowlist) VALUES (NULL);', check=False).returncode, 0)

    def test_repair_adds_missing_column_in_nonpublic_schema(self):
        self.sql('CREATE SCHEMA isolated; CREATE TABLE isolated.groups (id INT); INSERT INTO isolated.groups VALUES (1);')
        migration = (MIGRATIONS / '236_group_model_allowlist_repair.sql').read_text()
        self.sql('SET search_path TO isolated; ' + migration)
        self.assertEqual(self.sql('SELECT model_allowlist FROM isolated.groups;').stdout.strip(), b'{}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
