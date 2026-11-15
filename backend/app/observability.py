"""Bounded LangSmith spans with optional, redacted debugging content."""

import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from queue import Full, Queue
from threading import Thread
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)
_current = ContextVar("knowledge_trace_span", default=None)
_ALLOWED = {
    "request_id",
    "session_id",
    "attempt_no",
    "web_search",
    "mode",
    "provider",
    "model",
    "status",
    "error_code",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "returned",
    "results",
    "citations",
    "documents",
    "characters",
    "http_status",
}


def safe_metadata(values):
    return {
        k: v
        for k, v in values.items()
        if k in _ALLOWED
        and (v is None or type(v) in {bool, int, float} or isinstance(v, str) and len(v) <= 150)
    }


class Span:
    def __init__(self, tracer, name, kind="chain", metadata=None, parent=None):
        self.tracer, self.name, self.kind, self.parent = tracer, name, kind, parent
        self.metadata = metadata or {}
        self.id, self.start, self.end = str(uuid4()), datetime.now(UTC), None
        self.root = parent.root if parent else self
        if not parent:
            self.spans = []
            self.content_remaining = 500_000
        self.inputs, self.outputs = {}, {}
        self.order = (
            (parent.order + "." if parent else "")
            + self.start.strftime("%Y%m%dT%H%M%S%fZ")
            + self.id
        )
        self.token = None

    @property
    def recording(self):
        return bool(
            self.tracer and self.tracer.enabled and self.tracer.settings.langsmith_record_content
        )

    def record(self, *, inputs=None, outputs=None):
        if not self.recording:
            return
        for target, value in ((self.inputs, inputs), (self.outputs, outputs)):
            if value is None or self.root.content_remaining <= 0:
                continue
            budget = [min(120_000, self.root.content_remaining)]
            initial = budget[0]
            cleaned = self.tracer.clean(value, budget)
            target.update(cleaned if isinstance(cleaned, dict) else {"value": cleaned})
            self.root.content_remaining -= initial - budget[0]

    def __enter__(self):
        self.token = _current.set(self)
        if self.tracer and self.tracer.enabled:
            self.root.spans.append(self)
        return self

    def __exit__(self, kind, error, tb):
        self.end = datetime.now(UTC)
        if error:
            self.metadata.update(status="failed", error_code=getattr(error, "code", kind.__name__))
        if self.token is not None:
            _current.reset(self.token)
        if not self.parent and self.tracer:
            self.tracer.submit(self)

    def payload(self):
        metadata = safe_metadata(self.metadata)
        body = {
            "id": self.id,
            "name": self.name,
            "run_type": self.kind,
            "start_time": self.start.isoformat(),
            "end_time": (self.end or datetime.now(UTC)).isoformat(),
            "inputs": self.inputs,
            "outputs": {**self.outputs, "status": metadata.get("status", "completed")},
            "session_name": self.tracer.settings.langsmith_project,
            "trace_id": self.root.id,
            "dotted_order": self.order,
            "extra": {"metadata": {"content_recording": self.recording, **metadata}},
        }
        if self.parent:
            body["parent_run_id"] = self.parent.id
        if self.kind == "llm":
            inputs = metadata.get("input_tokens", metadata.get("prompt_tokens"))
            outputs = metadata.get("output_tokens", metadata.get("completion_tokens"))
            if isinstance(inputs, int) and isinstance(outputs, int):
                body["outputs"]["usage_metadata"] = {
                    "input_tokens": inputs,
                    "output_tokens": outputs,
                    "total_tokens": metadata.get("total_tokens", inputs + outputs),
                }
        if metadata.get("status") == "failed":
            body["error"] = metadata.get("error_code", "request_failed")
        return body


def start_span(name, kind="chain", **metadata):
    parent = _current.get()
    return Span(parent.tracer if parent else None, name, kind, metadata, parent)


class Tracer:
    def __init__(self, settings, *, http=None):
        self.settings, self.http = settings, http
        self.enabled = settings.langsmith_tracing and bool(
            settings.langsmith_api_key.get_secret_value()
        )
        self.queue, self.worker = Queue(maxsize=32), None
        self.secrets = []
        for name in (
            "langsmith_api_key",
            "tavily_api_key",
            "qwen_api_key",
            "monkey_api_key",
            "mineru_api_token",
            "s3_secret_key",
            "database_url",
        ):
            value = getattr(settings, name).get_secret_value()
            if len(value) >= 8:
                self.secrets.append(value)
        if self.enabled:
            try:
                url = urlsplit(settings.langsmith_endpoint)
                if (
                    url.scheme != "https"
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.query
                    or url.fragment
                ):
                    raise ValueError("invalid endpoint")
                self.endpoint = settings.langsmith_endpoint.rstrip("/")
            except Exception:
                self.enabled = False
                logger.warning("LangSmith disabled: invalid endpoint")
        if self.enabled:
            self.worker = Thread(target=self._export, name="langsmith-export", daemon=True)
            self.worker.start()

    def root(self, name, **metadata):
        return Span(self, name, metadata=metadata)

    def clean(self, value, budget, depth=0):
        if depth > 10 or budget[0] <= 0:
            return "[truncated]"
        if isinstance(value, dict):
            return {
                str(k): "[redacted]"
                if re.search(
                    r"^(?:api[_-]?key|authorization|password|secret(?:_key)?|access_key|token)$",
                    str(k),
                    re.I,
                )
                else self.clean(v, budget, depth + 1)
                for k, v in list(value.items())[:100]
            }
        if isinstance(value, (list, tuple)):
            return [self.clean(item, budget, depth + 1) for item in value[:100]]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            value = re.sub(r"\b(?:sk-|tvly-|lsv2_)[A-Za-z0-9_-]{8,}", "[redacted]", value)
            value = re.sub(
                r"(?i)((?:api[_-]?key|password|secret_key|access_key|token)\s*[:=]\s*)[^\s,;]+",
                r"\1[redacted]",
                value,
            )
            limit = min(100_000, budget[0])
            budget[0] -= min(len(value), limit)
            return value[:limit] + (" [truncated]" if len(value) > limit else "")
        if value is None or type(value) in {bool, int, float}:
            return value
        return str(type(value).__name__)

    def submit(self, root):
        if not self.enabled:
            return
        try:
            self.queue.put_nowait([span.payload() for span in root.spans[:64]])
        except Full:
            logger.warning("LangSmith trace dropped: export queue full")

    def _export(self):
        http = self.http or httpx.Client(
            timeout=httpx.Timeout(5, connect=3),
            trust_env=self.settings.langsmith_trust_env,
            follow_redirects=False,
        )
        try:
            while True:
                batch = self.queue.get()
                try:
                    if batch is None:
                        return
                    for body in batch:
                        response = http.post(
                            self.endpoint + "/runs",
                            headers={
                                "x-api-key": self.settings.langsmith_api_key.get_secret_value()
                            },
                            json=body,
                        )
                        response.raise_for_status()
                except Exception as error:
                    logger.warning("LangSmith export failed (%s)", type(error).__name__)
                finally:
                    self.queue.task_done()
        finally:
            if self.http is None:
                http.close()

    def flush(self):
        if self.worker:
            self.queue.join()

    def close(self):
        if self.worker:
            try:
                self.queue.put_nowait(None)
            except Full:
                logger.warning("LangSmith shutdown: exporter remains draining")
            self.worker.join(timeout=1)
