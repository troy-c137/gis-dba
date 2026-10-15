"""Rehearse baseline -> additive change -> rollback -> reapply in a NEW staging DB."""
import argparse
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from gis_dba.admin import ROOT, migrate
from gis_dba.config import database_url

parser = argparse.ArgumentParser()
parser.add_argument('--target', default='gis_restore_migration_rehearsal')
args = parser.parse_args()
if not args.target.startswith('gis_restore_') or len(args.target) > 60:
    parser.error('Use a new gis_restore_ database name (max 60 characters)')
dsn = database_url('ADMIN_DATABASE_URL')
with psycopg.connect(make_conninfo(dsn, dbname='postgres'), autocommit=True) as conn:
    # Existing targets fail rather than being overwritten.
    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(args.target)))
with psycopg.connect(make_conninfo(dsn, dbname=args.target)) as conn:
    conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(args.target)))
    migrate(conn, '001_core.sql')
    conn.execute((ROOT / 'sql/seed.sql').read_text(), prepare=False)
    baseline = conn.execute('SELECT equipment_id,asset_type FROM tracking.assets ORDER BY asset_id').fetchall()
with psycopg.connect(make_conninfo(dsn, dbname=args.target)) as conn:
    migrate(conn)
    conn.execute("UPDATE tracking.assets SET description='Synthetic staging rehearsal'")
    assert conn.execute('SELECT equipment_id,asset_type FROM tracking.assets ORDER BY asset_id').fetchall() == baseline
with psycopg.connect(make_conninfo(dsn, dbname=args.target), autocommit=True) as conn:
    conn.execute((Path(ROOT) / 'sql/rollback/002_asset_description.sql').read_text(), prepare=False)
    assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='tracking' "
                        "AND table_name='assets' AND column_name='description'").fetchone()[0] == 0
with psycopg.connect(make_conninfo(dsn, dbname=args.target)) as conn:
    migrate(conn)
    migrate(conn)  # Re-running is a no-op and validates checksums.
    assert conn.execute('SELECT equipment_id,asset_type FROM tracking.assets ORDER BY asset_id').fetchall() == baseline
print(f'MIGRATION REHEARSAL VERIFIED: {args.target}; baseline, apply, rollback, reapply, no-op')
