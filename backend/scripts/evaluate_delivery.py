"""Run delivery questions against the real API; gold answers never leave this process."""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx


def read_stream(client, body):
    started = monotonic()
    event, lines, deltas = "", [], 0
    with client.stream("POST", "/api/chat/stream", json=body) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                lines.append(line[5:].strip())
            elif not line and lines:
                data = json.loads("\n".join(lines))
                lines = []
                if event == "delta":
                    deltas += 1
                if event == "done":
                    return data["assistant"], round(monotonic() - started, 3), deltas
                if event == "error":
                    raise RuntimeError(data.get("message", "stream failed"))
    raise RuntimeError("stream ended without terminal state")


def evaluate(case, base_url):
    identity = str(uuid4())
    result = {
        "id": case["id"],
        "session_id": identity,
        "question": case["question"],
        "gold_answer": case.get("gold_answer"),
        "turns": [],
        "issues": [],
    }
    with httpx.Client(base_url=base_url, timeout=120) as client:
        try:
            client.post("/api/sessions", json={"id": identity}).raise_for_status()
            for question in case.get("turns", [case["question"]]):
                answer, elapsed, deltas = read_stream(
                    client,
                    {
                        "session_id": identity,
                        "client_request_id": str(uuid4()),
                        "text": question,
                        "web_search": case.get("web_search", False),
                    },
                )
                result["turns"].append(
                    {"question": question, "answer": answer, "seconds": elapsed, "deltas": deltas}
                )
            final = result["turns"][-1]["answer"]
            if final["status"] != "completed":
                result["issues"].append("incomplete")
            if final.get("answer_mode") != case["mode"]:
                result["issues"].append("unexpected_route")
            if case.get("refusal"):
                if final.get("answer_kind") not in ["refused", "partially_answered"]:
                    result["issues"].append("missing_refusal")
            elif case["mode"] == "knowledge" and not final["citations"]:
                result["issues"].append("missing_citation")
            if case["mode"] == "web" and not final.get("web_sources"):
                result["issues"].append("missing_web_source")
            for citation in final["citations"]:
                if citation["quote"] not in citation["source"]["content"]:
                    result["issues"].append("invalid_quote")
            for expression in case.get("checks", []):
                if not re.search(expression, final["content"], re.I):
                    result["issues"].append("fact_check:" + expression)
            if case.get("source_title") and not any(
                case["source_title"] in c["source"]["document_title"] for c in final["citations"]
            ):
                result["issues"].append("expected_source_not_cited")
        except Exception as error:
            result["issues"].append(type(error).__name__ + ": " + str(error))
        finally:
            response = client.delete("/api/sessions/" + identity)
            result["cleaned"] = response.status_code == 204
    result["basic_checks_passed"] = not result["issues"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8014")
    parser.add_argument("--cases", type=Path, default=Path("eval/delivery-cases.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    cases = [
        json.loads(line)
        for line in args.cases.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(evaluate, case, args.api) for case in cases]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            (args.output / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                result["id"],
                "basic-pass" if result["basic_checks_passed"] else "REVIEW",
                result["issues"],
                flush=True,
            )
    order = {case["id"]: i for i, case in enumerate(cases)}
    results.sort(key=lambda r: order[r["id"]])
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "cases": len(results),
        "basic_passed": sum(r["basic_checks_passed"] for r in results),
        "manual_review_required": True,
        "all_temporary_sessions_cleaned": all(r["cleaned"] for r in results),
    }
    (args.output / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        "# 交付问答首轮结果",
        "",
        "自动检查只验证路由、来源、拒答和少量事实，不等同于语义正确率；逐题人工复核见 review.md。",
        "",
        "| 编号 | 问题 | 基本检查 | 秒 |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        duration = sum(t["seconds"] for t in r["turns"])
        rows.append(
            f"| {r['id']} | {r['question']} | "
            f"{'通过' if r['basic_checks_passed'] else '需复核'} | {duration:.2f} |"
        )
    (args.output / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
