"""对自己的隔离服务执行真实模型闭环；凭据文件不得提交，不输出密钥或原始错误。"""

import argparse
import json
import os
import time
import uuid
from pathlib import Path

import httpx


def request_id():
    return str(uuid.uuid4())


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(
        description="真实模型与学习流程验收，会产生模型调用费用与测试学习记录"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/live-result.json"))
    args = parser.parse_args()
    for file in (args.password_file, args.credentials_file):
        if os.name == "posix" and file.stat().st_mode & 0o077:
            raise RuntimeError("凭据文件必须只允许当前用户读取（chmod 600）")
    credentials = json.loads(args.credentials_file.read_text())
    base = args.url.rstrip("/")
    records = []

    def step(name):
        records.append(name)
        print("已验证：" + name, flush=True)

    with httpx.Client(base_url=base, headers={"Origin": base}, timeout=240) as client:

        def call(method, path, **kwargs):
            response = client.request(method, "/api" + path, **kwargs)
            if response.status_code >= 400:
                value = response.json()
                raise RuntimeError(f"{path}失败：{value.get('detail', response.status_code)}")
            return response

        call("POST", "/login", json={"password": args.password_file.read_text().strip()})
        step("独立服务登录")
        imported = call("POST", "/examples").json()
        doc = imported["id"]
        duplicate = call("POST", "/examples").json()
        check(duplicate["duplicate"] and duplicate["id"] == doc, "示例重复导入不一致")
        state = call("GET", "/state").json()
        check(len([q for q in state["questions"] if q["document_id"] == doc]) >= 3, "示例题未就绪")
        for file in (Path("examples/backup-study.md"),):
            call("POST", "/documents", files={"file": (file.name, file.read_bytes())})
        check(
            call("GET", f"/documents/{doc}/original").content
            == Path("examples/backup-study.json").read_bytes(),
            "原文件不一致",
        )
        step("文件上传、示例导入、稳定身份与原文件下载")
        saved = call(
            "PUT", "/model", json={**credentials, "allow_no_key": False, "json_mode": True}
        ).json()
        check(saved["has_key"] and "api_key" not in saved, "密钥接口泄漏")
        call("POST", "/model/test")
        step("自配模型保存和真实连接测试")
        payload = {
            "request_id": request_id(),
            "question": "增量备份和差异备份有什么区别？请比较恢复时分别需要哪些备份。",
            "document_id": doc,
        }
        response = call("POST", "/ask", json=payload)
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        check(
            events[-1]["type"] == "done", "真实问答未完成：" + events[-1].get("message", "未知原因")
        )
        chat = events[-1]["chat"]
        check(chat["supported"] and chat["sources"], "真实问答没有有效引用")
        check("增量" in chat["answer"] and "差异" in chat["answer"], "真实回答没有比较两种备份")
        for source in chat["sources"]:
            chunk = call("GET", "/chunks/" + source["chunk_id"]).json()
            check(
                source["quote"] == chunk["text"] and source["version"] == chunk["version"],
                "出处文本或版本不一致",
            )
        replayed = call("POST", "/ask", json=payload)
        check('"replayed": true' in replayed.text, "问答没有复用同一完成结果")
        step("真实流式问答、引用定位与同一请求恢复")
        generated = call(
            "POST",
            "/questions/generate",
            json={
                "request_id": request_id(),
                "document_id": doc,
                "count": 3,
                "topic": "增量备份、差异备份和恢复演练",
            },
        ).json()
        check(generated["created"] + generated["duplicates"] == 3, "真实模型返回题数不符")
        state = call("GET", "/state").json()
        ai_questions = [q for q in state["questions"] if q["id"] in generated["ids"]]
        for question in ai_questions:
            check(not question["reviewed"] and question["origin"] == "ai", "AI题标识错误")
            for source in question["sources"]:
                check(
                    source["quote"] in call("GET", "/chunks/" + source["chunk_id"]).json()["text"],
                    "AI题出处不在原文",
                )
        step("真实生成3题、逐字出处核对及待人工审核标识")
        q = next(
            q
            for q in state["questions"]
            if q["origin"] == "example" and "周一做完整备份" in q["stem"]
        )
        first = call(
            "POST",
            f"/questions/{q['id']}/answer",
            json={"request_id": request_id(), "selected": [0]},
        ).json()
        check(not first["correct"], "示例错误答案判定异常")
        check(q["id"] in call("GET", "/state").json()["wrong_question_ids"], "错题未记录")
        correct_payload = {"request_id": request_id(), "selected": first["answer"]}
        corrected = call("POST", f"/questions/{q['id']}/answer", json=correct_payload).json()
        check(corrected["correct"], "错题纠正失败")
        before = call("GET", "/state").json()["stats"]["attempts_today"]
        check(
            call("POST", f"/questions/{q['id']}/answer", json=correct_payload).json() == corrected,
            "重复作答响应不一致",
        )
        check(call("GET", "/state").json()["stats"]["attempts_today"] == before, "重复作答增加记录")
        call("PUT", f"/questions/{q['id']}/marks", json={"favorite": True, "uncertain": True})
        if ai_questions:
            aiq = ai_questions[0]
            result = call(
                "POST",
                f"/questions/{aiq['id']}/answer",
                json={"request_id": request_id(), "selected": [0]},
            ).json()
            check(result["reference_only"], "未核对AI题不应冒充正式判分")
        step("参考练习、错题纠正、重复提交及收藏不确定记录")
        plan = call(
            "POST",
            "/plans",
            json={
                "request_id": request_id(),
                "daily_target": 3,
                "title": "备份知识学习计划",
                "document_id": doc,
            },
        ).json()
        state = call("GET", "/state").json()
        check(plan["tasks"] == len(state["tasks"]), "计划任务数量不一致")
        target = next(task for task in state["tasks"] if task["kind"] == "reading")
        call(
            "PUT",
            "/reading/" + target["target_id"],
            json={"completed": True, "offset": 180, "favorite": True},
        )
        state = call("GET", "/state").json()
        check(
            next(t for t in state["tasks"] if t["id"] == target["id"])["completed"],
            "阅读没有更新计划",
        )
        backup = call("GET", "/backup")
        check(
            credentials["api_key"] not in backup.text
            and "encrypted_key" not in backup.text
            and "password_hash" not in backup.text,
            "备份包含敏感凭据",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        (args.output.parent / "live-backup.json").write_bytes(backup.content)
        step("确定性学习计划、完成统计、阅读位置与无凭据备份")
        result = {
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "provider_model": credentials["model"],
            "steps": records,
            "documents": len(state["documents"]),
            "chunks": len(state["chunks"]),
            "questions": len(state["questions"]),
            "generated": generated,
            "source_locations": [
                {
                    "document_id": s["document_id"],
                    "chunk_id": s["chunk_id"],
                    "page": s["page"],
                    "section": s["section"],
                }
                for s in chat["sources"]
            ],
            "stats": state["stats"],
            "plan": plan,
            "limits": [
                "出处定位不等于答案语义核验",
                "AI题答案解析仍待人工核对",
                "本脚本不代替浏览器、容器或原生设备验收",
            ],
        }
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("真实模型流程已完成，结果已保存；未输出密钥。", flush=True)


if __name__ == "__main__":
    main()
