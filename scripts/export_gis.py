"""Export read-only GeoJSON layers for QGIS without embedding database credentials."""
import argparse
import json
from pathlib import Path

import psycopg

from gis_dba.config import database_url

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('artifacts/gis'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
queries = {
    'assets': """SELECT jsonb_build_object('type','Feature','id',asset_id,
        'geometry',ST_AsGeoJSON(geom)::jsonb,
        'properties',to_jsonb(a)-'geom'-'asset_id') FROM tracking.current_assets a ORDER BY asset_id""",
    'areas': """SELECT jsonb_build_object('type','Feature','id',area_id,
        'geometry',ST_AsGeoJSON(boundary)::jsonb,
        'properties',jsonb_build_object('name',name)) FROM tracking.operational_areas ORDER BY area_id""",
}
with psycopg.connect(database_url(), connect_timeout=5) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    for name, query in queries.items():
        features = [row[0] for row in conn.execute(query).fetchall()]
        path = args.output / f'{name}.geojson'
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2) + '\n')
        print(f'{path}: {len(features)} features')
