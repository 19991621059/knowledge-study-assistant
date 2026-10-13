"""仅浏览器检查使用的可控模型夹具；不是产品的示例模式或真实模型证据。"""

import json
import re
import shutil
from pathlib import Path

import httpx
import uvicorn
from study_assistant import main
from study_assistant.ai.provider import OpenAICompatibleProvider, ProviderConfig

folder = Path("artifacts/e2e-data")
if folder.exists():
    shutil.rmtree(folder)
app = main.create_app(folder)
app.state.security.set_password("browser-test-password-2026")


def handler(request):
    payload = json.loads(request.content)
    if payload["stream"]:
        text = "增量备份复制上一次备份以来变化的文件，恢复需要完整备份和之后的各次增量备份。差异备份复制最近一次完整备份以来的变化，恢复需要完整备份和最后一次差异备份。[S1]"
        frames = [
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": text[i : i + 7]}, "finish_reason": None}]},
                ensure_ascii=False,
            )
            + "\n\n"
            for i in range(0, len(text), 7)
        ]
        frames.append('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(
            200, content="".join(frames).encode(), headers={"content-type": "text/event-stream"}
        )
    text = "连接正常"
    count = re.search(r"生成(\d+)道", payload["messages"][-1]["content"])
    if count:
        source = app.state.store.query(
            "SELECT * FROM chunks WHERE text LIKE '%增量备份复制%' LIMIT 1"
        )[0]
        text = json.dumps(
            {
                "questions": [
                    {
                        "stem": f"生成的参考练习{i + 1}：增量备份恢复需要什么？",
                        "options": [
                            "仅最后一次备份",
                            "完整备份及各次增量",
                            "无需文件",
                            "只需目录名",
                        ],
                        "answer": [1],
                        "explanation": "增量备份仅包含上一次备份以来的变化，恢复需要完整备份及之后各次增量备份。",
                        "sources": [
                            {
                                "chunk_id": source["id"],
                                "quote": "增量备份复制上一次备份以来发生变化的文件",
                            }
                        ],
                    }
                    for i in range(int(count[1]))
                ]
            },
            ensure_ascii=False,
        )
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    )


def mock_provider(store, security):
    settings = store.get_setting("model", {})
    if not settings:
        return main.get_provider_original(store, security)
    return OpenAICompatibleProvider(
        ProviderConfig(
            api_key="fixture-only-key", base_url="https://model.example/v1", model="fixture-model"
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ), False


main.get_provider_original = main.get_provider
main.get_provider = mock_provider
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
