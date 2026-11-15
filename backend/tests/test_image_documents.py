import io
import json

import pytest
from PIL import Image
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_indexing_jobs import finish
from test_indexing_jobs import indexed_environment as indexed_environment
from test_parsing import archive

from app.importing.mineru import MinerUClient

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "extension,kind,mime", [("png", "PNG", "image/png"), ("jpeg", "JPEG", "image/jpeg")]
)
def test_image_original_ocr_index_and_fingerprint_share_the_existing_pipeline(
    indexed_environment, monkeypatch, extension, kind, mime
):
    client, settings, _ = indexed_environment
    stream = io.BytesIO()
    Image.new("RGB", (40, 50), "white").save(stream, format=kind)
    content = stream.getvalue()
    monkeypatch.setattr(
        MinerUClient,
        "submit",
        lambda *_: {"batch_id": "image", "upload_url": "https://mineru.net/upload"},
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
                ("full.md", "报销必须提交真实发票。"),
                (
                    "image_content_list.json",
                    json.dumps([{"type": "text", "text": "报销必须提交真实发票。", "page_idx": 0}]),
                ),
            ]
        ),
    )
    response = upload(client, content, filename="制度." + extension)
    assert response.status_code == 202, response.text
    accepted = response.json()
    original = client.get(f"/api/document-versions/{accepted['version_id']}/file")
    assert original.content == content and original.headers["content-type"] == mime
    duplicate = upload(client, content, filename="重命名." + extension).json()
    assert duplicate["duplicate"] and duplicate["document_id"] == accepted["document_id"]
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    path = f"/api/document-versions/{accepted['version_id']}"
    parsed = client.get(path + "/parsed").json()["result"]
    chunks = client.get(path + "/chunks").json()["items"]
    assert parsed["page_count"] == 1 and chunks
    assert all(source["page_start"] == source["page_end"] == 1 for source in chunks)
    assert "真实发票" in chunks[0]["content"]
