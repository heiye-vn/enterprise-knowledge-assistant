import json

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.observability import Tracer, start_span


def config(**values):
    return Settings(
        _env_file=None,
        langsmith_tracing=True,
        langsmith_api_key=SecretStr("private-trace-key"),
        langsmith_project="test-project",
        **values,
    )


def test_trace_exports_parent_child_metadata_and_never_raw_content():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(202)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tracer = Tracer(config(), http=http)
        with tracer.root(
            "chat", request_id="request", question="sensitive question", api_key="private-trace-key"
        ) as root:
            with start_span("intent", "chain", text="sensitive document"):
                with start_span("model", "llm", model="test", provider="qwen") as model:
                    model.metadata.update(input_tokens=10, output_tokens=3)
            root.metadata["status"] = "completed"
        tracer.flush()
        tracer.close()
    assert len(sent) == 3
    parent = next(p for p in sent if p["name"] == "chat")
    child = next(p for p in sent if p["name"] == "intent")
    llm = next(p for p in sent if p["name"] == "model")
    assert child["parent_run_id"] == parent["id"] and llm["parent_run_id"] == child["id"]
    assert llm["trace_id"] == parent["id"] and llm["dotted_order"].startswith(
        child["dotted_order"] + "."
    )
    serialized = json.dumps(sent)
    assert "sensitive" not in serialized and "private-trace-key" not in serialized
    assert llm["extra"]["metadata"]["input_tokens"] == 10


def test_disabled_or_unconfigured_tracing_never_sends_network_requests():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("network")))
    ) as http:
        for s in [config(langsmith_endpoint="https://trace.test"), Settings(_env_file=None)]:
            s.langsmith_tracing = False
            tracer = Tracer(s, http=http)
            with tracer.root("chat"):
                pass
            tracer.flush()
            tracer.close()


def test_trace_export_failure_never_fails_business_work():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="private-trace-key"))
    ) as http:
        tracer = Tracer(config(), http=http)
        with tracer.root("chat") as root:
            root.metadata["status"] = "completed"
        tracer.flush()
        tracer.close()
        assert root.metadata["status"] == "completed"


def test_content_recording_exports_question_evidence_and_answer_with_secrets_redacted():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(202)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tracer = Tracer(config(langsmith_record_content=True), http=http)
        with tracer.root("chat") as root:
            root.record(inputs={"question": "请问请假需要谁审批？ private-trace-key"})
            with start_span("knowledge.retrieve", "retriever") as retrieve:
                retrieve.record(
                    inputs={"query": "半天事假审批"},
                    outputs={"documents": [{"page_content": "不超过1个工作日由直属主管审批。"}]},
                )
            root.record(outputs={"answer": "由直属主管审批。[1]", "api_key": "must-never-export"})
        tracer.flush()
        tracer.close()
    parent = next(item for item in sent if item["name"] == "chat")
    assert (
        "请假" in parent["inputs"]["question"]
        and parent["outputs"]["answer"] == "由直属主管审批。[1]"
    )
    assert parent["extra"]["metadata"]["content_recording"] is True
    content = json.dumps(sent, ensure_ascii=False)
    assert (
        "不超过1个工作日" in content
        and "private-trace-key" not in content
        and "must-never-export" not in content
    )


def test_metadata_mode_discards_content_and_content_mode_is_bounded():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202))) as http:
        tracer = Tracer(config(), http=http)
        with tracer.root("chat") as root:
            root.record(
                inputs={"question": "must-not-record"}, outputs={"answer": "must-not-record"}
            )
        assert root.payload()["inputs"] == {} and "must-not-record" not in json.dumps(
            root.payload()
        )
        tracer.flush()
        tracer.close()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202))) as http:
        tracer = Tracer(config(langsmith_record_content=True), http=http)
        with tracer.root("chat") as root:
            root.record(outputs={"answer": "a" * 1_000_000})
        assert len(json.dumps(root.payload())) < 150_000 and "truncated" in root.outputs["answer"]
        tracer.flush()
        tracer.close()
