from fastapi.testclient import TestClient

from gis_dba.api import app

client = TestClient(app)


def test_liveness():
    assert client.get('/health/live').json() == {'status': 'alive'}


def test_authentication(monkeypatch):
    monkeypatch.setenv('API_KEY', 'test-key')
    assert client.get('/assets').status_code == 401
    assert client.get('/assets', headers={'X-API-Key': 'wrong'}).status_code == 401


def test_xml_limits_and_validation(monkeypatch):
    monkeypatch.setenv('API_KEY', 'test-key')
    headers = {'X-API-Key': 'test-key'}
    assert client.post('/telemetry/xml', content=b'x' * 16385, headers=headers).status_code == 413
    assert client.post('/telemetry/xml', content=b'<bad>', headers=headers).status_code == 422
    assert client.get('/assets/nearby?longitude=181&latitude=0', headers=headers).status_code == 422
