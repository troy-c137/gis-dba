"""Isolated disposable benchmark table, never drops application indexes."""
import argparse
import json
import time
from pathlib import Path

import psycopg

from gis_dba.config import database_url

parser = argparse.ArgumentParser()
parser.add_argument('--rows', type=int, default=100_000)
parser.add_argument('--output', default='artifacts/benchmark.json')
args = parser.parse_args()
if not 1_000 <= args.rows <= 1_000_000:
    parser.error('rows must be between 1,000 and 1,000,000')
queries = {
    'spatial': """SELECT count(*) FROM lab.benchmark_telemetry
        WHERE ST_DWithin(position,ST_SetSRID(ST_MakePoint(-140,-40),4326)::geography,1000)""",
    'asset_time': """SELECT * FROM lab.benchmark_telemetry WHERE asset_id=7
        AND observed_at >= '2026-01-01 00:00:00+00'::timestamptz + interval '1 day'
        ORDER BY observed_at DESC LIMIT 100""",
}
report = {'rows': args.rows, 'phases': {}}
with psycopg.connect(database_url('ADMIN_DATABASE_URL'), autocommit=True) as conn:
    conn.execute('SELECT pg_advisory_lock(7349018)')
    conn.execute('CREATE SCHEMA IF NOT EXISTS lab')
    conn.execute('DROP TABLE IF EXISTS lab.benchmark_telemetry')
    conn.execute('''CREATE TABLE lab.benchmark_telemetry AS
        SELECT i AS event_id, 1+(i%%100) AS asset_id,
        '2026-01-01 00:00:00+00'::timestamptz + i*interval '1 second' AS observed_at,
        ST_SetSRID(ST_MakePoint(-140 + ((i*37)%%10000)/25000.0 - 0.2,
                               -40 + ((i*53)%%10000)/25000.0 - 0.2),4326)::geography AS position
        FROM generate_series(1,%s) i''', (args.rows,))
    report['server'] = conn.execute('SELECT version(),PostGIS_Full_Version()').fetchone()
    for phase in ('before', 'after'):
        if phase == 'after':
            start = time.monotonic()
            conn.execute('CREATE INDEX benchmark_position_gix ON lab.benchmark_telemetry USING gist(position)')
            conn.execute('CREATE INDEX benchmark_asset_time_idx ON lab.benchmark_telemetry(asset_id,observed_at DESC)')
            report['index_build_seconds'] = time.monotonic() - start
        conn.execute('ANALYZE lab.benchmark_telemetry')
        report['phases'][phase] = {}
        for name, query in queries.items():
            # One warm-up followed by three measured plans; preserve timings/buffers and plan nodes.
            conn.execute(query).fetchall()
            report['phases'][phase][name] = [conn.execute(
                'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query).fetchone()[0][0]
                for _ in range(3)]
        report['phases'][phase]['relation_bytes'] = conn.execute(
            "SELECT pg_total_relation_size('lab.benchmark_telemetry')").fetchone()[0]
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2, default=str) + '\n')
for phase, queries in report['phases'].items():
    for name in ('spatial', 'asset_time'):
        print(phase, name, [round(p['Execution Time'], 3) for p in queries[name]], 'ms')
print(f'Full plans: {output}')
