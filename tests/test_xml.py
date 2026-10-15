from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from gis_dba.telemetry import InvalidTelemetry, parse_xml

EXAMPLE = Path('examples/telemetry.xml').read_bytes()


def changed(field, value):
    root = ET.fromstring(EXAMPLE)
    root.find(field).text = value
    return ET.tostring(root)


def test_valid():
    event = parse_xml(EXAMPLE)
    assert event.equipment_id == 'SIM-ASSET-001'
    assert event.latitude == -40.05
    assert event.observed_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize('field,value', [
    ('longitude', 'nan'), ('latitude', 'inf'), ('latitude', '91'),
    ('longitude', '-181'), ('battery_pct', '101'), ('battery_pct', '1.5'),
    ('status', 'mystery'), ('equipment_id', 'REAL-001'), ('message_id', 'bad'),
    ('observed_at', '2026-01-01T00:00:00'), ('observed_at', '2099-01-01T00:00:00Z'),
    ('source', ''),
])
def test_bad_values(field, value):
    with pytest.raises(InvalidTelemetry):
        parse_xml(changed(field, value))


@pytest.mark.parametrize('raw', [b'<bad>', b'\xff', b'x' * 16385,
    b'<!DOCTYPE telemetry [<!ENTITY x "test">]><telemetry>&x;</telemetry>',
    EXAMPLE.replace(b'</telemetry>', b'<status>online</status></telemetry>'),
    EXAMPLE.replace(b'<status>', b'<status extra="x">'),
    EXAMPLE.replace(b'<status>online</status>', b'<status><nested/></status>'),
    EXAMPLE.replace(b'<telemetry>', b'<telemetry xmlns="example">'),
])
def test_bad_documents(raw):
    with pytest.raises(InvalidTelemetry):
        parse_xml(raw)
