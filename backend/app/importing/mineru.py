"""Official MinerU v4 protocol. Credentials never accompany presigned resources."""

import logging
import time
from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings
from app.importing.parsing import ParseError

API = "https://mineru.net/api/v4"
RESOURCE_DOMAINS = ("mineru.net", "openxlab.org.cn", "aliyuncs.com")
logger = logging.getLogger(__name__)


def resource_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme == "https"
            and parts.port in {None, 443}
            and not parts.username
            and not parts.password
            and not parts.fragment
            and parts.hostname
            and any(
                parts.hostname == d or parts.hostname.endswith("." + d) for d in RESOURCE_DOMAINS
            )
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ParseError("mineru_resource_url", "解析服务返回了不支持的资源地址")
    return url


class MinerUClient:
    def __init__(self, settings: Settings, *, http=None):
        self.settings = settings
        self.http = http or httpx.Client(
            timeout=30, follow_redirects=False, trust_env=settings.model_trust_env
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def _api(self, method, path, *, body=None):
        token = self.settings.mineru_api_token.get_secret_value()
        if not token:
            raise ParseError("mineru_not_configured", "请先配置 MinerU Token，再重新解析")
        submitting = method == "POST"
        try:
            response = self.http.request(
                method,
                API + path,
                headers={"Authorization": "Bearer " + token},
                json=body,
            )
        except httpx.HTTPError:
            if submitting:
                raise ParseError(
                    "mineru_submission_unknown",
                    "无法确认远端任务是否创建，请核对 MinerU 控制台后重新解析",
                ) from None
            raise ParseError(
                "mineru_unavailable", "暂时无法查询解析服务，可重试", retryable=True
            ) from None
        if submitting and (response.status_code >= 500 or response.is_redirect):
            raise ParseError(
                "mineru_submission_unknown", "远端提交结果不确定，请核对 MinerU 控制台后重新解析"
            )
        if response.status_code in {401, 403}:
            raise ParseError("mineru_auth", "MinerU Token 无效或无权限，请更新配置后重新解析")
        if response.status_code >= 400:
            raise ParseError("mineru_unavailable", "解析服务请求失败，可稍后重试", retryable=True)
        try:
            value = response.json()
            code = value.get("code")
            if code != 0:
                if str(code) in {"A0202", "A0211"}:
                    raise ParseError(
                        "mineru_auth", "MinerU Token 无效或已过期，请更新配置后重新解析"
                    )
                raise ParseError("mineru_rejected", "MinerU 未接受该请求，请检查服务额度与任务状态")
            if not isinstance(value.get("data"), dict):
                raise ValueError
            return value["data"]
        except ParseError:
            raise
        except (ValueError, AttributeError):
            code = "mineru_submission_unknown" if submitting else "mineru_invalid_response"
            raise ParseError(code, "解析服务响应格式异常", retryable=not submitting) from None

    def submit(self, filename: str, data_id: str) -> dict:
        data = self._api(
            "POST",
            "/file-urls/batch",
            body={
                "files": [{"name": filename, "data_id": data_id}],
                "model_version": self.settings.mineru_model,
                "language": self.settings.mineru_language,
                "enable_table": True,
                "enable_formula": True,
            },
        )
        if not isinstance(data.get("batch_id"), str) or not data.get("file_urls"):
            raise ParseError(
                "mineru_submission_unknown", "远端任务身份未确认，请核对 MinerU 控制台后重新解析"
            )
        return {"batch_id": data["batch_id"], "upload_url": resource_url(data["file_urls"][0])}

    def upload(self, url: str, content: bytes):
        try:
            response = self.http.put(resource_url(url), content=content)
            response.raise_for_status()
        except httpx.HTTPError:
            raise ParseError(
                "mineru_upload_failed", "云端原件上传未确认，可重试同一任务", retryable=True
            ) from None

    def poll(self, batch_id: str, data_id: str) -> dict:
        data = self._api("GET", "/extract-results/batch/" + quote(batch_id, safe=""))
        for item in data.get("extract_result", []):
            if isinstance(item, dict) and item.get("data_id") == data_id:
                if item.get("state") == "failed":
                    raise ParseError(
                        "mineru_parse_failed", "MinerU 解析失败，请检查原件或云端任务详情"
                    )
                if item.get("state") not in {
                    "done",
                    "pending",
                    "running",
                    "waiting-file",
                    "converting",
                }:
                    raise ParseError(
                        "mineru_invalid_response", "无法识别远端任务状态", retryable=True
                    )
                return item
        raise ParseError("mineru_result_missing", "远端响应未包含当前文档", retryable=True)

    def download(self, url: str, *, max_bytes=50 * 1024 * 1024) -> bytes:
        start = time.monotonic()
        try:
            with self.http.stream("GET", resource_url(url)) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", "0")) > max_bytes:
                    raise ParseError("archive_too_large", "解析归档超过大小限制")
                chunks, size = [], 0
                for chunk in response.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes or time.monotonic() - start > 60:
                        raise ParseError("archive_too_large", "解析归档超过下载限制")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as error:
            logger.warning(
                "MinerU download interrupted (%s, HTTP %s)",
                type(error).__name__,
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else "unavailable",
            )
            raise ParseError(
                "mineru_download_failed", "暂时无法获取解析归档，可重试", retryable=True
            ) from None
        except ParseError:
            raise
        except ValueError:
            raise ParseError(
                "mineru_invalid_response", "解析归档响应格式异常", retryable=True
            ) from None
