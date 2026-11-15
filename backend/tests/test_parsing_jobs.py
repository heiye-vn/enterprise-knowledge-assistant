import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_parsing import archive

pytestmark = pytest.mark.integration


def test_markdown_persists_fixed_job_result_without_claiming_query_ready(
    import_environment, test_engine
):
    from app.models import Document, DocumentContent, DocumentVersion
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(
        client, "# 制度\n\n| 金额 | 岗位 |\n| --- | --- |\n| 500 | 主管 |".encode()
    ).json()
    process_document(accepted["job_id"], settings)
    response = client.get(f"/api/document-versions/{accepted['version_id']}/parsed")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["job_id"] == accepted["job_id"]
    assert body["result"]["blocks"][1]["rows"][1][0]["text"] == "500"
    assert body["latest_processing"]["display_status"] == "parsed"
    assert body["result"]["page_count"] is None
    summary = client.get(f"/api/documents/{accepted['document_id']}").json()
    assert summary["status"] == "parsed" and summary["can_query"] is False
    assert not {"blocks", "markdown"}.intersection(summary)
    with Session(test_engine) as db:
        assert db.get(Document, UUID(accepted["document_id"])).current_version_id is None
        assert db.get(DocumentVersion, UUID(accepted["version_id"])).active_import_job_id is None
        assert db.scalar(
            select(DocumentContent).where(DocumentContent.job_id == UUID(accepted["job_id"]))
        )


def test_reprocess_is_idempotent_rejects_active_and_retains_previous_result(import_environment):
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()
    path = f"/api/document-versions/{accepted['version_id']}"
    active = client.post(path + "/reprocess", json={"job_id": str(uuid4())})
    assert active.status_code == 409
    assert active.json()["detail"]["job_id"] == accepted["job_id"]
    process_document(accepted["job_id"], settings)
    request_id = str(uuid4())
    response = client.post(path + "/reprocess", json={"job_id": request_id})
    assert response.status_code == 202, response.text
    assert response.json()["job_id"] == request_id
    assert client.post(path + "/reprocess", json={"job_id": request_id}).json() == response.json()
    assert client.get(path + "/parsed").json()["result"]["job_id"] == accepted["job_id"]
    process_document(request_id, settings)
    assert client.get(path + "/parsed").json()["result"]["job_id"] == request_id
    assert (
        client.get(path + f"/parsed?job_id={accepted['job_id']}").json()["result"]["generation_no"]
        == 1
    )
    other = upload(client, b"other").json()
    assert (
        client.post(
            f"/api/document-versions/{other['version_id']}/reprocess", json={"job_id": request_id}
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/api/document-versions/{other['version_id']}/parsed?job_id={request_id}"
        ).status_code
        == 404
    )


def pdf():
    from pypdf import PdfWriter

    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.write(out)
    return out.getvalue()


def test_remote_poll_continuations_do_not_use_attempts_and_keep_original_page_count(
    import_environment, test_engine, monkeypatch
):
    from app.importing.mineru import MinerUClient
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client, pdf(), filename="real.pdf").json()
    calls = []
    monkeypatch.setattr(
        MinerUClient,
        "submit",
        lambda *_: (
            calls.append("submit")
            or {"batch_id": "remote", "upload_url": "https://mineru.net/upload"}
        ),
    )
    monkeypatch.setattr(MinerUClient, "upload", lambda *_: calls.append("upload"))
    states = iter(["pending"] * 4 + ["done"])
    monkeypatch.setattr(
        MinerUClient,
        "poll",
        lambda *_: {"state": next(states), "full_zip_url": "https://mineru.net/result"},
    )
    monkeypatch.setattr(
        MinerUClient,
        "download",
        lambda *_: archive(
            [
                ("full.md", "text"),
                ("x_content_list.json", '[{"type":"text","text":"正文","page_idx":0}]'),
            ]
        ),
    )
    settings = settings.model_copy(update={"mineru_api_token": SecretStr("unit-token")})
    for _ in range(5):
        process_document(accepted["job_id"], settings)
        with Session(test_engine) as db, db.begin():
            job = db.get(ProcessingJob, UUID(accepted["job_id"]))
            assert job.attempt_no == 1
            cp = dict(job.checkpoint)
            cp["resume_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            job.checkpoint = cp
    assert calls == ["submit", "upload"]
    body = client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()
    assert body["result"]["page_count"] == 2  # Includes trailing blank page.
    assert body["result"]["blocks"][0]["page_start"] == 1


def test_unknown_submission_checkpoint_never_creates_another_remote_task(
    import_environment, test_engine, monkeypatch
):
    from app.importing.mineru import MinerUClient
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client, pdf(), filename="real.pdf").json()
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(accepted["job_id"])).checkpoint = {
            "mineru": {
                "phase": "submitting",
                "deadline": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            }
        }
    monkeypatch.setattr(MinerUClient, "submit", lambda *_: pytest.fail("must not resubmit"))
    process_document(accepted["job_id"], settings)
    job = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert job["error"]["code"] == "mineru_submission_unknown"
    assert not job["error"]["retryable"]


def test_remote_deadline_is_bounded(import_environment, test_engine):
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client, pdf(), filename="deadline.pdf").json()
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(accepted["job_id"])).checkpoint = {
            "mineru": {
                "phase": "polling",
                "batch_id": "remote",
                "deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        }
    process_document(accepted["job_id"], settings)
    job = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert job["error"]["code"] == "mineru_deadline"


def test_legacy_parser_job_is_explicitly_reprocessed_with_current_configuration(
    import_environment, test_engine
):
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(accepted["job_id"])).config = {"parser": "not-configured"}
    process_document(accepted["job_id"], settings)
    old = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert old["error"]["code"] == "parser_not_configured"
    identity = str(uuid4())
    response = client.post(
        f"/api/document-versions/{accepted['version_id']}/reprocess", json={"job_id": identity}
    )
    assert response.status_code == 202
    process_document(identity, settings)
    assert (
        client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()["result"][
            "job_id"
        ]
        == identity
    )


def test_expired_worker_cannot_publish_parsed_results(import_environment, test_engine, monkeypatch):
    from app.models import ProcessingJob
    from app.tasks import documents

    client, settings, _ = import_environment
    accepted = upload(client).json()
    original = documents.parse_markdown

    def expire(content):
        result = original(content)
        with Session(test_engine) as db, db.begin():
            db.get(ProcessingJob, UUID(accepted["job_id"])).lease_expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
        return result

    monkeypatch.setattr(documents, "parse_markdown", expire)
    documents.process_document(accepted["job_id"], settings)
    assert (
        client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()["result"]
        is None
    )


def test_remote_assets_are_fixed_to_manifest_and_old_orphans_are_removed(
    import_environment, monkeypatch
):
    from app.importing.mineru import MinerUClient
    from app.tasks.dispatch import cleanup_orphans
    from app.tasks.documents import process_document

    client, settings, storage = import_environment
    accepted = upload(client, pdf(), filename="image.pdf").json()
    image = b"\x89PNG\r\n\x1a\nqa-image"
    monkeypatch.setattr(
        MinerUClient,
        "submit",
        lambda *_: {"batch_id": "remote", "upload_url": "https://mineru.net/upload"},
    )
    monkeypatch.setattr(MinerUClient, "upload", lambda *_: None)
    monkeypatch.setattr(
        MinerUClient,
        "poll",
        lambda *_: {"state": "done", "full_zip_url": "https://mineru.net/result"},
    )
    monkeypatch.setattr(
        MinerUClient,
        "download",
        lambda *_: archive(
            [
                ("full.md", "image"),
                (
                    "x_content_list.json",
                    '[{"type":"image","img_path":"images/a.png","page_idx":0}]',
                ),
                ("images/a.png", image),
            ]
        ),
    )
    process_document(accepted["job_id"], settings)
    result = client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()["result"]
    url = result["blocks"][0]["asset_url"]
    response = client.get(url)
    assert response.content == image and response.headers["content-type"] == "image/png"
    assert client.get(url.rsplit("/", 1)[0] + "/unregistered").status_code == 404
    orphan = settings.parsed_prefix + "/orphan.zip"
    storage.put(orphan, b"orphan", "application/zip", "a" * 64)
    assert cleanup_orphans(settings, cutoff=datetime.now(UTC) + timedelta(seconds=5)) == 1
    assert client.get(url).content == image


def test_reprocess_concurrency_accepts_only_one_new_generation(import_environment):
    from concurrent.futures import ThreadPoolExecutor

    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()
    process_document(accepted["job_id"], settings)
    path = f"/api/document-versions/{accepted['version_id']}/reprocess"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: client.post(path, json={"job_id": str(uuid4())}), range(2))
        )
    assert sorted(r.status_code for r in responses) == [202, 409]


def test_poll_retry_resumes_existing_batch_without_reupload(
    import_environment, test_engine, monkeypatch
):
    from app.importing.mineru import MinerUClient
    from app.importing.parsing import ParseError
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client, pdf(), filename="resume.pdf").json()
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(accepted["job_id"])).checkpoint = {
            "mineru": {
                "phase": "uploading",
                "batch_id": "original-batch",
                "upload_url": "https://mineru.net/upload",
                "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }
        }
    monkeypatch.setattr(MinerUClient, "submit", lambda *_: pytest.fail("must not resubmit"))
    monkeypatch.setattr(MinerUClient, "upload", lambda *_: pytest.fail("remote already processing"))

    def unavailable(*_):
        raise ParseError("mineru_unavailable", "暂不可用", retryable=True)

    monkeypatch.setattr(MinerUClient, "poll", unavailable)
    process_document(accepted["job_id"], settings)
    assert client.post(f"/api/processing-jobs/{accepted['job_id']}/retry").status_code == 200

    def finished(self, batch, data_id):
        assert batch == "original-batch" and data_id == accepted["job_id"]
        return {"state": "done", "full_zip_url": "https://mineru.net/result"}

    monkeypatch.setattr(MinerUClient, "poll", finished)
    monkeypatch.setattr(
        MinerUClient,
        "download",
        lambda *_: archive(
            [
                ("full.md", "resumed"),
                ("x_content_list.json", '[{"type":"text","text":"resumed","page_idx":0}]'),
            ]
        ),
    )
    process_document(accepted["job_id"], settings)
    body = client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()
    assert body["result"]["markdown"] == "resumed"
    assert body["latest_processing"]["attempt_no"] == 2


def test_completed_remote_download_resumes_after_parsing_deadline(
    import_environment, test_engine, monkeypatch
):
    from app.importing.mineru import MinerUClient
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client, pdf(), filename="download-resume.pdf").json()
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(accepted["job_id"])).checkpoint = {
            "mineru": {
                "phase": "downloading",
                "batch_id": "done-batch",
                "archive_url": "https://mineru.net/result",
                "deadline": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "download_deadline": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        }
    monkeypatch.setattr(MinerUClient, "submit", lambda *_: pytest.fail("must not submit"))
    monkeypatch.setattr(MinerUClient, "poll", lambda *_: pytest.fail("already completed"))
    monkeypatch.setattr(
        MinerUClient,
        "download",
        lambda *_: archive(
            [
                ("full.md", "downloaded"),
                ("x_content_list.json", '[{"type":"text","text":"done","page_idx":0}]'),
            ]
        ),
    )
    process_document(accepted["job_id"], settings)
    body = client.get(f"/api/document-versions/{accepted['version_id']}/parsed").json()
    assert body["result"] and body["result"]["markdown"] == "downloaded"
