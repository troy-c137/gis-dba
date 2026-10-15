import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from gis_dba.config import database_url

ROOT = Path(os.getenv('GIS_PROJECT_ROOT', Path(__file__).resolve().parents[2]))


def migrate(conn, target=None):
    # One transaction for the requested batch; advisory lock also covers first-run creation.
    conn.execute('SELECT pg_advisory_xact_lock(7349017)')
    conn.execute('''CREATE TABLE IF NOT EXISTS public.schema_migrations(
        version text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())''')
    conn.execute('REVOKE ALL ON public.schema_migrations FROM PUBLIC')
    files = sorted((ROOT / 'sql/migrations').glob('*.sql'))
    if not files:
        raise ValueError('No migrations found; run from an editable checkout or set GIS_PROJECT_ROOT')
    if target and target not in {p.name for p in files}:
        raise ValueError('Unknown migration target')
    applied = dict(conn.execute('SELECT version,sha256 FROM public.schema_migrations').fetchall())
    for path in files:
        body = path.read_text()
        digest = hashlib.sha256(body.encode()).hexdigest()
        if path.name in applied:
            if applied[path.name] != digest:
                raise ValueError(f'Applied migration changed: {path.name}')
        elif not target or path.name <= target:
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute(body, prepare=False)
            conn.execute('INSERT INTO public.schema_migrations(version,sha256) VALUES (%s,%s)',
                         (path.name, digest))
            print(f'Applied {path.name}')


def roles(conn):
    # Cluster roles persist across databases; privileges below are scoped to this database.
    for role in ('gis_reader', 'gis_ingest', 'gis_monitor'):
        password = os.environ.get(role.upper() + '_PASSWORD')
        if not password or len(password) < 20:
            raise ValueError(f'{role.upper()}_PASSWORD must contain at least 20 characters')
        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                             'NOREPLICATION NOBYPASSRLS PASSWORD {}').format(
                                 sql.Identifier(role), sql.Literal(password)))
    db = conn.info.dbname
    conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db)))
    conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO gis_reader,gis_ingest,gis_monitor')
                 .format(sql.Identifier(db)))
    conn.execute('GRANT USAGE ON SCHEMA tracking TO gis_reader,gis_ingest,gis_monitor')
    conn.execute('GRANT SELECT ON tracking.current_assets,tracking.assets_in_areas,'
                 'tracking.operational_areas TO gis_reader,gis_monitor')
    conn.execute('REVOKE ALL ON FUNCTION tracking.ingest(uuid,text,timestamptz,'
                 'double precision,double precision,text,smallint,text) FROM PUBLIC')
    conn.execute('GRANT EXECUTE ON FUNCTION tracking.ingest(uuid,text,timestamptz,'
                 'double precision,double precision,text,smallint,text) TO gis_ingest')
    conn.execute('GRANT pg_monitor TO gis_monitor')
    for role in ('gis_reader', 'gis_ingest', 'gis_monitor'):
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'")
                     .format(sql.Identifier(role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'")
                     .format(sql.Identifier(role)))


def env_file():
    path = ROOT / '.env'
    if path.exists():
        raise ValueError('.env already exists; refusing to overwrite credentials')
    values = {name: secrets.token_hex(24) for name in
              ('POSTGRES_PASSWORD', 'GIS_READER_PASSWORD', 'GIS_INGEST_PASSWORD',
               'GIS_MONITOR_PASSWORD', 'API_KEY')}
    text = (ROOT / '.env.example').read_text()
    for name, value in values.items():
        text = text.replace(f'<{name}>', value)
    # Create atomically with restrictive permissions.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(text)
    print('Created .env with random credentials (mode 0600)')


def health(conn):
    row = conn.execute('''SELECT current_database(), version(),
        (SELECT extversion FROM pg_extension WHERE extname='postgis'),
        (SELECT count(*) FROM tracking.current_assets),
        (SELECT max(observed_at) FROM tracking.current_assets),
        (SELECT count(*) FROM pg_locks WHERE NOT granted)''').fetchone()
    print(json.dumps(dict(zip(('database', 'postgres', 'postgis', 'assets',
                               'latest_observation', 'waiting_locks'), row)), default=str, indent=2))
    if not row[2]:
        raise ValueError('PostGIS missing')


def main():
    parser = argparse.ArgumentParser(description='Admin tasks; run from the repository checkout')
    parser.add_argument('command', choices=['env', 'create-db', 'migrate', 'roles', 'seed', 'health'])
    parser.add_argument('--target', help='Stop migration batch at this filename')
    args = parser.parse_args()
    try:
        if args.command == 'env':
            env_file()
            return
        dsn = database_url('MONITOR_DATABASE_URL' if args.command == 'health' else 'ADMIN_DATABASE_URL')
        if args.command == 'create-db':
            details = conninfo_to_dict(dsn)
            dbname = details.get('dbname', 'gis_lab')
            with psycopg.connect(make_conninfo(dsn, dbname='postgres'), autocommit=True) as conn:
                if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (dbname,)).fetchone():
                    conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
            print(f'Database ready: {dbname}')
            return
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            if args.command == 'migrate':
                migrate(conn, args.target)
            elif args.command == 'roles':
                roles(conn)
            elif args.command == 'seed':
                conn.execute((ROOT / 'sql/seed.sql').read_text(), prepare=False)
            elif args.command == 'health':
                health(conn)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')
    except psycopg.Error as exc:
        # Do not print connection strings or SQL statements carrying passwords.
        parser.exit(1, f'{type(exc).__name__}: administration failed; check configuration and database logs\n')


if __name__ == '__main__':
    main()
