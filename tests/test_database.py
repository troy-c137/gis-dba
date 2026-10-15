import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from gis_dba.api import app
from gis_dba.config import database_url
from gis_dba.telemetry import INGEST_SQL, parse_xml

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Set RUN_DB_TESTS=1')]


@pytest.fixture
def event():
    original = parse_xml(Path('examples/telemetry.xml').read_bytes())
    event = replace(original, message_id=uuid4(), equipment_id='SIM-TEST-ASSET',
                    observed_at=original.observed_at + timedelta(seconds=10))
    with psycopg.connect(database_url('ADMIN_DATABASE_URL')) as conn:
        unit_id = conn.execute("SELECT unit_id FROM tracking.units WHERE code='SIM-ALPHA'").fetchone()[0]
        conn.execute("INSERT INTO tracking.assets(equipment_id,unit_id,asset_type) VALUES (%s,%s,'sensor')",
                     (event.equipment_id, unit_id))
    yield event
    with psycopg.connect(database_url('ADMIN_DATABASE_URL')) as conn:
        asset_id = conn.execute('SELECT asset_id FROM tracking.assets WHERE equipment_id=%s',
                                (event.equipment_id,)).fetchone()[0]
        conn.execute('DELETE FROM tracking.current_state WHERE asset_id=%s', (asset_id,))
        conn.execute('DELETE FROM tracking.telemetry_events WHERE asset_id=%s', (asset_id,))
        conn.execute('DELETE FROM tracking.assets WHERE asset_id=%s', (asset_id,))


def ingest(event):
    with psycopg.connect(database_url('INGEST_DATABASE_URL')) as conn:
        return conn.execute(INGEST_SQL, event.parameters()).fetchone()[0]


def test_retry_order_conflict_atomicity(event):
    assert ingest(event)
    assert not ingest(event)
    assert ingest(replace(event, message_id=uuid4(), observed_at=event.observed_at-timedelta(seconds=1)))
    with psycopg.connect(database_url()) as conn:
        row = conn.execute('SELECT message_id FROM tracking.current_assets WHERE equipment_id=%s',
                           (event.equipment_id,)).fetchone()
        assert row[0] == event.message_id
    with pytest.raises(psycopg.errors.UniqueViolation):
        ingest(replace(event, longitude=-141))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        ingest(replace(event, message_id=uuid4(), equipment_id='SIM-UNKNOWN'))
    invalid = replace(event, message_id=uuid4(), status='invalid')
    with pytest.raises(psycopg.errors.CheckViolation):
        ingest(invalid)
    with psycopg.connect(database_url('ADMIN_DATABASE_URL')) as conn:
        assert conn.execute('SELECT count(*) FROM tracking.telemetry_events WHERE message_id=%s',
                            (invalid.message_id,)).fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM tracking.locations WHERE message_id=%s',
                            (invalid.message_id,)).fetchone()[0] == 0


def test_concurrent_duplicate_and_late_updates(event):
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sorted(pool.map(ingest, [event]*6)) == [False]*5 + [True]
        updates = [replace(event, message_id=uuid4(), observed_at=event.observed_at+timedelta(seconds=i))
                   for i in range(1, 10)]
        assert all(pool.map(ingest, reversed(updates)))
    with psycopg.connect(database_url()) as conn:
        assert conn.execute('SELECT message_id FROM tracking.current_assets WHERE equipment_id=%s',
                            (event.equipment_id,)).fetchone()[0] == updates[-1].message_id


def test_roles_and_spatial_api(event):
    ingest(event)
    with psycopg.connect(database_url()) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM tracking.assets")
    with psycopg.connect(database_url('INGEST_DATABASE_URL')) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM tracking.telemetry_events')
    client = TestClient(app)
    headers = {'X-API-Key': os.environ['API_KEY']}
    response = client.get('/assets/nearby?longitude=-140.05&latitude=-40.05&radius_m=10', headers=headers)
    assert response.status_code == 200
    assert event.equipment_id in [f['properties']['equipment_id'] for f in response.json()['features']]
    assert client.get('/health/ready').status_code == 200
    areas = client.get('/areas', headers=headers).json()['features']
    west = next(a for a in areas if a['properties']['name'] == 'Synthetic West')
    features = client.get(f"/areas/{west['id']}/assets", headers=headers).json()['features']
    assert event.equipment_id in [f['properties']['equipment_id'] for f in features]


def test_xml_api_write_and_retry(event):
    from xml.etree import ElementTree as ET

    root = ET.fromstring(Path('examples/telemetry.xml').read_bytes())
    root.find('message_id').text = str(event.message_id)
    root.find('equipment_id').text = event.equipment_id
    raw = ET.tostring(root)
    client = TestClient(app)
    headers = {'X-API-Key': os.environ['API_KEY'], 'Content-Type': 'application/xml'}
    response = client.post('/telemetry/xml', content=raw, headers=headers)
    assert response.status_code == 200
    assert response.json()['inserted'] is True
    assert client.post('/telemetry/xml', content=raw, headers=headers).json()['inserted'] is False
    root.find('latitude').text = '-41'
    assert client.post('/telemetry/xml', content=ET.tostring(root), headers=headers).status_code == 409
    root.find('message_id').text = str(uuid4())
    root.find('equipment_id').text = 'SIM-UNKNOWN'
    assert client.post('/telemetry/xml', content=ET.tostring(root), headers=headers).status_code == 422
