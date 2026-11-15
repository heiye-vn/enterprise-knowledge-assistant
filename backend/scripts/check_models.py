"""Explicit live checks using synthetic text only; never called by health checks or tests."""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from app.config import Settings  # noqa: E402
from app.model_clients import ModelClient, ModelProblem  # noqa: E402


def cosine(left, right):
    return sum(x * y for x, y in zip(left, right, strict=True)) / (
        math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    )


def check(settings, providers, streaming, operation="all"):
    results = []

    def run(provider, operation, model, action):
        try:
            value = action()
            result = {
                "provider": provider,
                "operation": operation,
                "model": model,
                "ok": True,
                **value,
            }
        except ModelProblem as problem:
            result = {
                "provider": provider,
                "operation": operation,
                "model": model,
                "ok": False,
                "code": problem.code,
                "message": str(problem),
                "retryable": problem.retryable,
            }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    with ModelClient(settings) as models:
        if "qwen" in providers:

            def embedding():
                batch = models.embed_texts(
                    ["报销应提供合规发票及审批记录。", "请假应提前向主管提交申请。"]
                )
                query = models.embed_texts(["报销需要什么材料？"], text_type="query")
                scores = [cosine(query.vectors[0], v) for v in batch.vectors]
                if scores[0] <= scores[1]:
                    raise ModelProblem("semantic_check_failed", "向量相关性验收未通过")
                return {
                    "count": len(batch.vectors),
                    "dimensions": [len(v) for v in batch.vectors],
                    "relevant_document_ranked_first": True,
                    "usage": batch.usage,
                    "query_usage": query.usage,
                }

            if operation in {"all", "embedding"}:
                run("qwen", "embedding", settings.embedding_model, embedding)

            def rerank():
                ranking = models.rerank(
                    "报销需要什么材料？",
                    ["天气晴朗，适合出游。", "报销应提供合规发票及审批记录。"],
                    top_n=2,
                )
                if ranking.items[0].index != 1:
                    raise ModelProblem("semantic_check_failed", "重排未将相关文档排在首位")
                return {"indexes": [item.index for item in ranking.items], "usage": ranking.usage}

            if operation in {"all", "rerank"}:
                run("qwen", "rerank", settings.qwen_rerank_model, rerank)

        for provider in providers:
            if operation not in {"all", "chat"}:
                continue
            model = settings.qwen_llm_model if provider == "qwen" else settings.monkey_llm_model

            def completion(provider=provider):
                reply = models.complete(
                    [{"role": "user", "content": "Reply only OK."}],
                    provider=provider,
                    max_tokens=512,
                )
                if reply.content.strip().rstrip(".") != "OK":
                    raise ModelProblem("semantic_check_failed", "回答未通过固定测试指令")
                return {"visible_answer_verified": True, "usage": reply.usage}

            run(provider, "chat", model, completion)

            if streaming:

                def stream(provider=provider):
                    content = "".join(
                        models.stream(
                            [{"role": "user", "content": "Reply only OK."}],
                            provider=provider,
                            max_tokens=512,
                        )
                    )
                    if content.strip().rstrip(".") != "OK":
                        raise ModelProblem("semantic_check_failed", "流式回答未通过固定测试指令")
                    return {"visible_answer_verified": True, "stream_terminated": True}

                run(provider, "chat_stream", model, stream)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="使用固定测试文本显式验证模型配置；会产生少量调用。"
    )
    parser.add_argument("--provider", choices=["qwen", "monkey", "all"], default=None)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument(
        "--operation", choices=["all", "embedding", "rerank", "chat"], default="all"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        settings = Settings()
    except ValidationError:
        print(json.dumps({"ok": False, "code": "invalid_model_configuration"}))
        return 1
    provider = args.provider or settings.llm_provider
    if provider == "monkey" and args.operation in {"embedding", "rerank"}:
        parser.error("Embedding/Rerank 使用 qwen，请选择 --provider qwen")
    results = check(
        settings,
        ["qwen", "monkey"] if provider == "all" else [provider],
        args.stream,
        args.operation,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
