import json
import re
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from study_assistant.ai.provider import OpenAICompatibleProvider, ProviderConfig
from study_assistant.main import create_app

PASSWORD = "local-test-password-2026"
ORIGIN = {"Origin": "http://testserver"}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    app.state.security.set_password(PASSWORD)
    with TestClient(app, headers=ORIGIN) as value:
        assert value.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield value


@pytest.fixture
def seeded(client):
    result = client.post("/api/examples")
    assert result.status_code == 200, result.text
    return client, result.json()["id"]


@pytest.fixture
def mock_model(monkeypatch, client):
    from study_assistant import main

    controls = {
        "calls": 0,
        "broken": False,
        "invalid_citation": False,
        "bad_quote": False,
        "truncated": False,
        "unauthorized": False,
    }

    def handler(request):
        controls["calls"] += 1
        if controls["unauthorized"]:
            return httpx.Response(401, json={"error": "sensitive-upstream-response-do-not-leak"})
        payload = json.loads(request.content)
        if payload["stream"]:
            answer = (
                "增量备份需要完整备份及之后的所有增量文件。[S99]"
                if controls["invalid_citation"]
                else "增量备份需要完整备份及之后的所有增量文件；差异备份需要完整备份和最后一次差异备份。[S1]"
            )
            frames = []
            for i in range(0, len(answer), 5):
                event = {
                    "model": "test-model",
                    "choices": [{"delta": {"content": answer[i : i + 5]}, "finish_reason": None}],
                }
                frames.append("data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n")
            if not controls["broken"]:
                frames.append(
                    'data: {"model":"test-model","choices":[{"delta":{},"finish_reason":"stop"}]}\r\n\r\n'
                )
                frames.append("data: [DONE]\r\n\r\n")
            return httpx.Response(
                200, content="".join(frames).encode(), headers={"content-type": "text/event-stream"}
            )
        prompt = payload["messages"][-1]["content"]
        match = re.search(r"生成(\d+)道", prompt)
        text = "连接正常"
        if match:
            chunk = client.app.state.store.query(
                "SELECT * FROM chunks WHERE text LIKE '%增量备份复制%' LIMIT 1"
            )[0]
            quote = (
                "引用了不存在的原文，应该被拒绝"
                if controls["bad_quote"]
                else "增量备份复制上一次备份以来发生变化的文件"
            )
            questions = [
                {
                    "stem": f"增量备份练习{i + 1}：恢复时需要哪些备份？",
                    "options": [
                        "仅最后一次增量备份",
                        "完整备份和之后的各次增量备份",
                        "不需要备份",
                        "仅周一日志",
                    ],
                    "answer": [1],
                    "explanation": "增量只复制上一次备份以来的变化，恢复需完整备份及全部后续增量备份。",
                    "sources": [{"chunk_id": chunk["id"], "quote": quote}],
                }
                for i in range(int(match[1]))
            ]
            text = json.dumps({"questions": questions}, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {"content": text},
                        "finish_reason": "length" if controls["truncated"] else "stop",
                    }
                ],
            },
        )

    provider = OpenAICompatibleProvider(
        ProviderConfig(
            api_key="fake-test-key", base_url="https://model.example/v1", model="test-model"
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(main, "get_provider", lambda *_: (provider, False))
    return controls


def operation():
    return str(uuid.uuid4())
