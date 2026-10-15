"""Manage a project-local PostgreSQL 17 cluster with SCRAM authentication."""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.pgdata'
parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['start', 'stop', 'status'])
args = parser.parse_args()
pg_bin = Path(os.environ.get('PG_BIN', '/opt/homebrew/opt/postgresql@17/bin'))
if not pg_bin.exists():
    pg_ctl = shutil.which('pg_ctl')
    if not pg_ctl:
        parser.error('Set PG_BIN to the PostgreSQL 17 bin directory')
    pg_bin = Path(pg_ctl).parent
version = subprocess.check_output([str(pg_bin / 'postgres'), '--version'], text=True)
if ' 17.' not in version:
    parser.error('This project requires PostgreSQL 17')
if args.command == 'start':
    if not (DATA / 'PG_VERSION').exists():
        password = os.environ.get('POSTGRES_PASSWORD')
        if not password:
            parser.error('Run gis-admin env first')
        with tempfile.NamedTemporaryFile(mode='w') as password_file:
            password_file.write(password + '\n')
            password_file.flush()
            subprocess.run([str(pg_bin / 'initdb'), '-D', str(DATA), '-U', 'postgres',
                            '--auth=scram-sha-256', '--pwfile', password_file.name,
                            '--encoding=UTF8', '--locale=C'], check=True)
    # pg_ctl itself refuses a second start; never silently attach to an unrelated server.
    subprocess.run([str(pg_bin / 'pg_ctl'), '-D', str(DATA), '-l', str(DATA / 'server.log'),
                    '-o', (f'-h 127.0.0.1 -p 5432 -k {DATA} '
                    '-c log_min_duration_statement=250 -c log_lock_waits=on '
                    '-c shared_preload_libraries=pg_stat_statements'), 'start', '-w'], check=True)
else:
    subprocess.run([str(pg_bin / 'pg_ctl'), '-D', str(DATA), args.command], check=True)
print('Native cluster uses 127.0.0.1:5432; use scripts/use_database.py native for host clients')
