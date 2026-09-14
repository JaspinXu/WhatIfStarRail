from fastapi.testclient import TestClient

from astral_agents.bridge_api import create_app

TOKEN = "test-token-with-at-least-24-characters"


def test_bridge_auth_ingest_and_export(tmp_path):
    client = TestClient(create_app(tmp_path / "bridge.sqlite", TOKEN))
    assert client.get("/v1/nodes").status_code == 401
    assert client.get("/v1/nodes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    client.headers["Authorization"] = "Bearer " + TOKEN
    assert client.get("/v1/health").json()["status"] == "ready"
    event = {"source": "ocr", "timeline": "t1", "event_id": "e1",
             "text": "你好", "cast": "三月七"}
    response = client.post("/v1/ingest", json=event)
    assert response.status_code == 200
    assert response.json()["created"]
    node_id = response.json()["id"]
    assert client.post("/v1/ingest", json=event).json() == {"id": node_id, "created": False}
    assert client.post("/v1/ingest", json=event | {"text": "改过"}).status_code == 409
    archive = client.get("/v1/branches/" + node_id).json()
    assert len(archive["nodes"]) == 1
    assert client.post("/v1/import", json=archive).status_code == 201
    assert client.get("/v1/nodes?q=你好&limit=1").json()["total"] == 2
    assert len(client.get("/v1/nodes?limit=1").json()["items"]) == 1
    assert client.get("/v1/branches/missing").status_code == 404


def test_bridge_rejects_invalid_requests(tmp_path):
    client = TestClient(create_app(tmp_path / "invalid.sqlite", TOKEN),
                        headers={"Authorization": "Bearer " + TOKEN})
    assert client.post("/v1/nodes", json={"title": "x", "content": "x", "cast": "，"}).status_code == 422
    assert client.post("/v1/nodes", json={"title": "x", "content": "x", "cast": "丹恒", "parent": "missing"}).status_code == 400
    assert client.post("/v1/ingest", content=b"x" * (8 * 1024 * 1024 + 1)).status_code == 413
    assert client.get("/v1/nodes").json()["total"] == 0
