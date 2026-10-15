import json
import os
import secrets

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from gis_dba.config import database_url
from gis_dba.telemetry import INGEST_SQL, MAX_XML_BYTES, InvalidTelemetry, parse_xml

app = FastAPI(title='Synthetic Geospatial Asset Lab', version='0.1.0')


def authenticate(x_api_key: str = Header(default='')) -> None:
    expected = os.getenv('API_KEY', '')
    if not expected:
        raise HTTPException(503, 'API_KEY is not configured')
    if not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, 'Invalid API key')


@app.get('/health/live')
def live():
    return {'status': 'alive'}


@app.get('/health/ready')
def ready():
    try:
        with psycopg.connect(database_url(), connect_timeout=3,
                             options='-c statement_timeout=5000') as conn:
            conn.execute('SELECT 1 FROM tracking.current_assets LIMIT 1').fetchall()
        return {'status': 'ready'}
    except (psycopg.Error, RuntimeError):
        raise HTTPException(503, 'Database unavailable or schema not initialized') from None


@app.post('/telemetry/xml', dependencies=[Depends(authenticate)])
async def ingest(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_XML_BYTES:
            raise HTTPException(413, 'XML exceeds 16 KiB')
    try:
        event = parse_xml(bytes(body))
    except InvalidTelemetry as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        async with await psycopg.AsyncConnection.connect(
            database_url('INGEST_DATABASE_URL'), connect_timeout=5,
            options='-c statement_timeout=10000 -c lock_timeout=5000'
        ) as conn:
            cursor = await conn.execute(INGEST_SQL, event.parameters())
            inserted = (await cursor.fetchone())[0]
        return {'message_id': str(event.message_id), 'inserted': inserted}
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, 'Message ID reused with different content') from None
    except (psycopg.errors.ForeignKeyViolation, psycopg.errors.CheckViolation,
            psycopg.errors.InvalidParameterValue):
        raise HTTPException(422, 'Unknown equipment or invalid telemetry values') from None
    except psycopg.Error:
        raise HTTPException(503, 'Database ingestion unavailable; retry the same message ID') from None


def feature_collection(where: str = '', params: tuple = (), limit: int = 1000):
    # Only server-owned SQL fragments are interpolated; all caller values are bound.
    with psycopg.connect(database_url(), connect_timeout=5,
                         options='-c statement_timeout=10000') as conn:
        rows = conn.execute(f'''
            SELECT jsonb_build_object('type','Feature','id',asset_id,
                'geometry', ST_AsGeoJSON(geom)::jsonb,
                'properties', to_jsonb(a) - 'geom' - 'asset_id')
            FROM tracking.current_assets a {where} ORDER BY asset_id LIMIT %s
        ''', (*params, limit)).fetchall()
    return {'type': 'FeatureCollection', 'features': [row[0] for row in rows]}


@app.get('/assets', dependencies=[Depends(authenticate)])
def assets(limit: int = Query(1000, ge=1, le=10000)):
    return feature_collection(limit=limit)


@app.get('/assets/nearby', dependencies=[Depends(authenticate)])
def nearby(longitude: float = Query(ge=-180, le=180),
           latitude: float = Query(ge=-90, le=90),
           radius_m: float = Query(10000, gt=0, le=100000),
           limit: int = Query(1000, ge=1, le=10000)):
    return feature_collection('''WHERE ST_DWithin(geom::geography,
        ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)''',
        (longitude, latitude, radius_m), limit)


@app.get('/areas/{area_id}/assets', dependencies=[Depends(authenticate)])
def in_area(area_id: int, limit: int = Query(1000, ge=1, le=10000)):
    return feature_collection('''WHERE EXISTS (SELECT 1 FROM tracking.operational_areas p
        WHERE p.area_id=%s AND ST_Covers(p.boundary,a.geom))''', (area_id,), limit)


@app.get('/areas', dependencies=[Depends(authenticate)])
def areas():
    with psycopg.connect(database_url(), connect_timeout=5) as conn:
        rows = conn.execute('''SELECT area_id,name,ST_AsGeoJSON(boundary)
                               FROM tracking.operational_areas ORDER BY area_id''').fetchall()
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': row[0], 'properties': {'name': row[1]},
         'geometry': json.loads(row[2])} for row in rows]}


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, exc: psycopg.Error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={'detail': 'Database query unavailable'})
