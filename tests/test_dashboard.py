"""Dashboard API route tests."""
import pytest
from unittest.mock import patch


@pytest.fixture
def client():
    """Create a FastAPI test client with a temporary database."""
    import tempfile
    import os
    from pathlib import Path
    from memento.db import get_connection, init_db

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()

        with patch.dict(os.environ, {"MEMENTO_DB": str(db_path)}):
            from memento.dashboard.server import create_app
            from fastapi.testclient import TestClient
            app = create_app()
            yield TestClient(app)


def _capture(origin="human", type_="fact", content="test memory"):
    """Helper: capture a memory directly into engrams table (non-awake mode)."""
    import os
    from pathlib import Path
    from memento.api import LocalAPI
    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]), use_awake=False)
    result = api.capture(content, type=type_, origin=origin)
    api.close()
    # Non-awake mode returns engram_id string directly
    return result


# ── Index ──

def test_app_serves_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Memento" in resp.text


# ── Status ──

def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "active" in data


# ── Engrams List ──

def test_list_engrams_empty(client):
    resp = client.get("/api/engrams")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_engrams_with_data(client):
    _capture(content="memory one", type_="fact")
    _capture(content="memory two", type_="decision", origin="agent")
    resp = client.get("/api/engrams")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert "id" in item
        assert "content" in item
        assert "type" in item
        assert "strength" in item


def test_list_engrams_filter_by_type(client):
    _capture(content="a fact", type_="fact")
    _capture(content="a decision", type_="decision")
    resp = client.get("/api/engrams?type=fact")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["type"] == "fact"


def test_list_engrams_filter_by_origin(client):
    _capture(content="human mem", origin="human")
    _capture(content="agent mem", origin="agent")
    resp = client.get("/api/engrams?origin=agent")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["origin"] == "agent"


def test_list_engrams_sort_and_limit(client):
    for i in range(5):
        _capture(content=f"memory {i}")
    resp = client.get("/api/engrams?limit=2&sort=created_at&order=asc")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ── Engram Detail ──

def test_get_engram_detail(client):
    eid = _capture(content="detail test")
    resp = client.get(f"/api/engrams/{eid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == eid
    assert "nexus" in data


def test_get_engram_not_found(client):
    resp = client.get("/api/engrams/nonexistent-id")
    assert resp.status_code == 404


# ── Verify / Forget / Pin ──

def test_verify_engram(client):
    eid = _capture(content="agent mem to verify", origin="agent")
    resp = client.post(f"/api/engrams/{eid}/verify")
    assert resp.status_code == 200


def test_forget_engram(client):
    eid = _capture(content="mem to forget")
    resp = client.delete(f"/api/engrams/{eid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True or data.get("status") == "pending"


def test_pin_engram(client):
    eid = _capture(content="mem to pin")
    resp = client.post(f"/api/engrams/{eid}/pin", json={"rigidity": 0.8})
    assert resp.status_code == 200


def test_pin_engram_invalid_rigidity(client):
    resp = client.post("/api/engrams/some-id/pin", json={"rigidity": 1.5})
    assert resp.status_code == 400


# ── Sessions ──

def test_get_sessions(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Epoch ──

def test_get_epoch_history(client):
    resp = client.get("/api/epoch/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_epoch_debt(client):
    resp = client.get("/api/epoch/debt")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_epoch_run(client):
    resp = client.post("/api/epoch/run", json={"mode": "light"})
    assert resp.status_code == 200


# ── Search (q parameter) ──

def test_search_engrams_with_q(client):
    """GET /api/engrams?q=keyword uses recall path."""
    _capture(content="python is great for scripting")
    _capture(content="rust is great for systems")
    resp = client.get("/api/engrams?q=python")
    assert resp.status_code == 200
    data = resp.json()
    # Should return results (recall may or may not find matches depending on embedding)
    assert isinstance(data, list)


def test_search_engrams_with_q_and_type_filter(client):
    """GET /api/engrams?q=keyword&type=fact applies post-filter on search results."""
    _capture(content="database indexing tips", type_="fact")
    _capture(content="database migration decision", type_="decision")
    resp = client.get("/api/engrams?q=database&type=fact")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # All results should be of type 'fact' if any returned
    for item in data:
        assert item["type"] == "fact"


# ── Captures Pending ──

def test_get_pending_captures(client):
    resp = client.get("/api/captures/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
