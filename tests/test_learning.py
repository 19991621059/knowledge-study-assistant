import json

from conftest import ORIGIN, PASSWORD, ROOT, operation
from fastapi.testclient import TestClient
from study_assistant.main import create_app


def test_import_duplicate_and_stable_identity(seeded):
    client, document_id = seeded
    initial = client.get("/api/state").json()
    second = client.post("/api/examples").json()
    assert second == {"id": document_id, "duplicate": True}
    assert initial["stats"]["questions"] == 3
    assert len(client.get("/api/state").json()["documents"]) == 1
    assert (
        client.get(f"/api/documents/{document_id}/original").content
        == (ROOT / "examples/backup-study.json").read_bytes()
    )


def test_invalid_bank_is_atomic(client):
    bundle = json.loads((ROOT / "examples/backup-study.json").read_bytes())
    bundle["questions"][1]["answer"] = [50]
    response = client.post(
        "/api/documents",
        files={"file": ("invalid.json", json.dumps(bundle).encode(), "application/json")},
    )
    assert response.status_code == 422
    assert not client.get("/api/state").json()["documents"]


def test_unverified_quote_is_rejected(client):
    bundle = json.loads((ROOT / "examples/backup-study.json").read_bytes())
    bundle["questions"][0]["sources"][0]["quote"] = "这是资料里不存在的引用文本"
    response = client.post(
        "/api/documents", files={"file": ("bad-source.json", json.dumps(bundle).encode())}
    )
    assert response.status_code == 422
    assert not client.get("/api/state").json()["documents"]


def test_invalid_unhashable_answer_is_rejected_atomically(client):
    bundle = json.loads((ROOT / "examples/backup-study.json").read_bytes())
    bundle["questions"][1]["answer"] = [{"invalid": "answer"}]
    response = client.post(
        "/api/documents", files={"file": ("invalid-answer.json", json.dumps(bundle).encode())}
    )
    assert response.status_code == 422
    assert not client.get("/api/state").json()["documents"]


def test_answer_idempotence_and_wrong_to_correct(seeded):
    client, _ = seeded
    question = client.get("/api/state").json()["questions"][0]
    assert "answer" not in question and "explanation" not in question
    qid = question["id"]
    actual = json.loads(
        client.app.state.store.query("SELECT answer FROM questions WHERE id=?", (qid,))[0]["answer"]
    )
    wrong = [(actual[0] + 1) % len(question["options"])]
    payload = {"request_id": operation(), "selected": wrong}
    first = client.post(f"/api/questions/{qid}/answer", json=payload)
    repeat = client.post(f"/api/questions/{qid}/answer", json=payload)
    assert first.status_code == 200 and not first.json()["correct"]
    assert first.json() == repeat.json()
    assert len(client.app.state.store.query("SELECT * FROM attempts")) == 1
    assert client.get("/api/state").json()["stats"]["wrong"] == 1
    conflict = client.post(f"/api/questions/{qid}/answer", json={**payload, "selected": actual})
    assert conflict.status_code == 409
    corrected = client.post(
        f"/api/questions/{qid}/answer", json={"request_id": operation(), "selected": actual}
    )
    assert corrected.json()["correct"]
    assert client.get("/api/state").json()["stats"]["wrong"] == 0
    assert len(client.app.state.store.query("SELECT * FROM attempts")) == 2


def test_reveal_does_not_fake_progress(seeded):
    client, _ = seeded
    qid = client.get("/api/state").json()["questions"][0]["id"]
    response = client.post(
        f"/api/questions/{qid}/answer",
        json={"request_id": operation(), "selected": [], "mode": "reveal"},
    )
    assert response.status_code == 200
    result = client.get("/api/state").json()
    assert result["stats"]["practiced"] == 0
    assert result["stats"]["correct"] == 0
    assert result["questions"][0]["revealed"]


def test_plan_counts_completion_and_replay(seeded):
    client, doc = seeded
    request = {"request_id": operation(), "daily_target": 3, "document_id": doc}
    plan = client.post("/api/plans", json=request)
    assert plan.status_code == 200, plan.text
    assert client.post("/api/plans", json=request).json() == plan.json()
    data = client.get("/api/state").json()
    assert plan.json()["tasks"] == len(data["chunks"]) + 3
    ids = [task["target_id"] for task in data["tasks"]]
    assert len(ids) == len(set(ids))
    chunk = data["chunks"][0]
    client.put("/api/reading/" + chunk["id"], json={"completed": True, "offset": 125})
    refreshed = client.get("/api/state").json()
    assert sum(t["completed"] for t in refreshed["tasks"]) == 1
    rebuilt = client.post("/api/plans", json={**request, "request_id": operation()}).json()
    assert rebuilt["tasks"] == plan.json()["tasks"] - 1
    assert client.get("/api/state").json()["stats"]["read"] == 1


def test_persistence_drafts_marks_and_reopen(seeded):
    client, _ = seeded
    data = client.get("/api/state").json()
    cid = data["chunks"][0]["id"]
    qid = data["questions"][0]["id"]
    client.put("/api/reading/" + cid, json={"completed": True, "offset": 312, "favorite": True})
    client.put(f"/api/questions/{qid}/draft", json={"selected": [0]})
    client.put(f"/api/questions/{qid}/marks", json={"favorite": True, "uncertain": True})
    folder = client.app.state.store.folder
    with TestClient(create_app(folder), headers=ORIGIN) as reopened:
        assert reopened.post("/api/login", json={"password": PASSWORD}).status_code == 200
        state = reopened.get("/api/state").json()
        assert next(c for c in state["chunks"] if c["id"] == cid)["offset"] == 312
        question = next(q for q in state["questions"] if q["id"] == qid)
        assert question["draft"] == [0] and question["favorite"] and question["uncertain"]
        assert reopened.get("/api/chunks/" + cid).json()["offset"] == 312


def test_backup_restore_excludes_secrets_and_rolls_back(seeded, tmp_path):
    client, _ = seeded
    client.put(
        "/api/model",
        json={
            "base_url": "https://model.example/v1",
            "model": "example-model",
            "api_key": "never-copy-me-to-backup",
        },
    )
    data = client.get("/api/state").json()
    client.put("/api/reading/" + data["chunks"][0]["id"], json={"completed": True})
    backup = client.get("/api/backup")
    assert backup.status_code == 200
    assert "never-copy-me" not in backup.text and "encrypted_key" not in backup.text
    assert "password_hash" not in backup.text and "sessions" not in backup.text
    with TestClient(create_app(tmp_path / "restored"), headers=ORIGIN) as target:
        target.app.state.security.set_password(PASSWORD)
        target.post("/api/login", json={"password": PASSWORD})
        broken = backup.json()
        broken["tables"]["chunks"][0]["document_id"] = "missing"
        failed = target.post(
            "/api/backup/restore", files={"file": ("broken.json", json.dumps(broken).encode())}
        )
        assert failed.status_code == 422
        assert not target.get("/api/state").json()["documents"]
        valid = target.post("/api/backup/restore", files={"file": ("backup.json", backup.content)})
        assert valid.status_code == 200, valid.text
        restored = target.get("/api/state").json()
        assert restored["stats"]["read"] == 1 and restored["stats"]["questions"] == 3
        assert not restored["model"]["configured"]
        assert (
            target.post(
                "/api/backup/restore", files={"file": ("backup.json", backup.content)}
            ).status_code
            == 409
        )
