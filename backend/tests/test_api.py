import json
import threading
from fastapi.testclient import TestClient
from app import api


def test_demo_stream_contains_progress_and_valid_report():
    with TestClient(api.app) as client:
        response = client.post('/research', json={'question': 'Why have Microsoft operating margins changed?', 'mode': 'demo'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]['type'] == 'started'
    assert any(e['type'] == 'progress' and e['phase'] == 'plan' for e in events)
    report = events[-1]['report']
    assert report['synthetic'] and report['complete']
    assert report['findings'] and report['sources'][0]['uri']
    assert not api.busy


def test_validation_and_missing_configuration(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    with TestClient(api.app) as client:
        assert client.post('/research', json={'question': '   '}).status_code == 422
        assert client.post('/research', json={'question': 'Research MSFT'}).status_code == 503
        assert client.get('/health').json()['sec_configured'] is False


def test_failure_stream_releases_slot(monkeypatch):
    def fail(*args):
        raise RuntimeError('private implementation detail')
    monkeypatch.setattr(api, 'perform_research', fail)
    with TestClient(api.app) as client:
        result = client.post('/research', json={'question': 'Research MSFT', 'mode': 'demo'})
    events = [json.loads(line) for line in result.text.splitlines()]
    assert events[-1]['type'] == 'error'
    assert 'private implementation detail' not in result.text
    assert not api.busy


def test_concurrent_run_rejected_while_health_responds(monkeypatch):
    started, release = threading.Event(), threading.Event()
    def block(*args):
        started.set()
        assert release.wait(5)
        return {'complete': False}
    monkeypatch.setattr(api, 'perform_research', block)
    with TestClient(api.app) as client:
        worker = threading.Thread(target=lambda: client.post('/research', json={'question': 'Research MSFT', 'mode': 'demo'}))
        worker.start()
        try:
            assert started.wait(3)
            assert client.get('/health').json()['busy']
            assert client.post('/research', json={'question': 'Research NVDA', 'mode': 'demo'}).status_code == 409
        finally:
            release.set()
            worker.join(5)
    assert not api.busy
