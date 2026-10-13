import json

from conftest import ORIGIN, PASSWORD, operation
from fastapi.testclient import TestClient


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_streamed_grounded_answer_and_replay(seeded, mock_model):
    client, doc = seeded
    payload = {
        "request_id": operation(),
        "question": "增量备份和差异备份的区别",
        "document_id": doc,
    }
    response = client.post("/api/ask", json=payload)
    data = events(response)
    assert any(e["type"] == "delta" for e in data)
    chat = data[-1]["chat"]
    assert chat["supported"] and chat["sources"]
    source = chat["sources"][0]
    chunk = client.get("/api/chunks/" + source["chunk_id"]).json()
    assert source["quote"] == chunk["text"]
    assert source["version"] == chunk["version"]
    again = events(client.post("/api/ask", json=payload))[-1]
    assert again["replayed"] and mock_model["calls"] == 1


def test_unrelated_question_does_not_invent_source(seeded, mock_model):
    client, _ = seeded
    data = events(
        client.post("/api/ask", json={"request_id": operation(), "question": "zephyrquantumxyz"})
    )
    assert not data[-1]["chat"]["supported"]
    assert not data[-1]["chat"]["sources"]
    assert mock_model["calls"] == 0


def test_invalid_source_and_interrupted_stream_not_saved(seeded, mock_model):
    client, _ = seeded
    for failure in ("invalid_citation", "broken"):
        mock_model[failure] = True
        response = client.post(
            "/api/ask", json={"request_id": operation(), "question": "增量备份的内容"}
        )
        data = events(response)
        assert data[-1]["type"] == "error"
        assert not client.get("/api/state").json()["chats"]
        mock_model[failure] = False


def test_generation_checked_atomic_and_idempotent(seeded, mock_model):
    client, doc = seeded
    payload = {"request_id": operation(), "document_id": doc, "count": 2}
    first = client.post("/api/questions/generate", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 2
    assert client.post("/api/questions/generate", json=payload).json() == first.json()
    assert mock_model["calls"] == 1
    generated = [q for q in client.get("/api/state").json()["questions"] if q["origin"] == "ai"]
    assert len(generated) == 2 and all(not q["reviewed"] for q in generated)
    mock_model["bad_quote"] = True
    bad = client.post("/api/questions/generate", json={**payload, "request_id": operation()})
    assert bad.status_code == 422
    assert client.get("/api/state").json()["stats"]["questions"] == 5
    mock_model["bad_quote"] = False
    mock_model["truncated"] = True
    assert (
        client.post(
            "/api/questions/generate", json={**payload, "request_id": operation()}
        ).status_code
        == 502
    )


def test_secret_storage_public_response_and_change_address(client):
    secret = "private-key-used-only-in-this-test"
    response = client.put(
        "/api/model",
        json={"base_url": "https://model.example/v1", "model": "example", "api_key": secret},
    )
    assert response.status_code == 200
    assert secret not in response.text and "encrypted_key" not in response.text
    config = client.app.state.store.get_setting("model")
    assert config["encrypted_key"] != secret
    assert client.app.state.security.decrypt(config["encrypted_key"]) == secret
    assert secret.encode() not in client.app.state.store.path.read_bytes()
    assert secret not in client.get("/api/state").text
    assert (
        client.put(
            "/api/model", json={"base_url": "https://other.example/v1", "model": "other"}
        ).status_code
        == 422
    )
    local = client.put(
        "/api/model",
        json={
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "local-model",
            "allow_no_key": True,
            "clear_key": True,
        },
    )
    assert local.status_code == 200 and not local.json()["has_key"]
    assert (
        client.put(
            "/api/model",
            json={"base_url": "http://unsafe.example/v1", "model": "other", "allow_no_key": True},
        ).status_code
        == 503
    )


def test_upstream_errors_are_sanitized(seeded, mock_model):
    client, _ = seeded
    mock_model["unauthorized"] = True
    response = client.post("/api/model/test")
    assert response.status_code == 503
    assert "认证失败" in response.json()["detail"]
    assert "sensitive-upstream" not in response.text


def test_auth_origin_cookie_and_revocation(client):
    with TestClient(client.app) as anonymous:
        assert anonymous.get("/api/state").status_code == 401
        assert anonymous.post("/api/login", json={"password": PASSWORD}).status_code == 403
        assert (
            anonymous.post(
                "/api/login",
                json={"password": PASSWORD},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        login = anonymous.post("/api/login", json={"password": PASSWORD}, headers=ORIGIN)
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        token = anonymous.cookies.get("study_session")
        assert anonymous.post("/api/logout", headers=ORIGIN).status_code == 200
        anonymous.cookies.set("study_session", token)
        assert anonymous.get("/api/state").status_code == 401


def test_strict_answer_rejects_bool_and_duplicate_options(seeded):
    client, _ = seeded
    qid = client.get("/api/state").json()["questions"][0]["id"]
    assert (
        client.post(
            f"/api/questions/{qid}/answer", json={"request_id": operation(), "selected": [True]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/questions/{qid}/answer", json={"request_id": operation(), "selected": [0, 0]}
        ).status_code
        == 422
    )
