from io import BytesIO
from zipfile import ZipFile

import pytest


@pytest.mark.parametrize(
    "filename,content",
    [
        ("fake.pdf", b"not a PDF"),
        ("fake.docx", b"not a zip"),
        ("binary.md", b"\x00binary"),
        ("blank.md", b" \n"),
        ("old.doc", b"data"),
    ],
)
def test_invalid_file_is_rejected_before_storage(filename, content):
    from app.importing.validation import InvalidUpload, validate_file

    with pytest.raises(InvalidUpload):
        validate_file(filename, content, max_bytes=20 * 1024 * 1024)


def test_size_limit_and_real_docx_signature():
    from app.importing.validation import InvalidUpload, validate_file

    with pytest.raises(InvalidUpload):
        validate_file("large.md", b"abcd", max_bytes=3)
    data = BytesIO()
    with ZipFile(data, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
    assert validate_file("制度.DOCX", data.getvalue(), max_bytes=10000).format == "docx"


def test_markdown_keeps_unicode_filename_and_does_not_claim_pdf_pages():
    from app.importing.validation import validate_file

    value = validate_file("制度.md", "# 制度\n正文".encode(), max_bytes=1000)
    assert value.filename == "制度.md"
    assert value.mime_type.startswith("text/markdown")


@pytest.mark.parametrize(
    "extension,kind,mime",
    [("png", "PNG", "image/png"), ("jpg", "JPEG", "image/jpeg"), ("jpeg", "JPEG", "image/jpeg")],
)
def test_real_policy_images_are_accepted_and_jpeg_extension_is_normalized(extension, kind, mime):
    from PIL import Image

    from app.importing.validation import validate_file

    stream = BytesIO()
    Image.new("RGB", (32, 32), "white").save(stream, format=kind)
    value = validate_file("制度." + extension, stream.getvalue(), max_bytes=10000)
    assert value.mime_type == mime
    assert value.format == ("jpg" if extension == "jpeg" else extension)


@pytest.mark.parametrize("content", [b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
def test_broken_policy_images_are_rejected(content):
    from app.importing.validation import InvalidUpload, validate_file

    with pytest.raises(InvalidUpload):
        validate_file("制度.png", content, max_bytes=10000)


def test_image_signature_must_match_extension_and_pixel_budget_is_bounded():
    import struct
    import zlib

    from PIL import Image

    from app.importing.validation import InvalidUpload, validate_file

    stream = BytesIO()
    Image.new("RGB", (32, 32), "white").save(stream, format="PNG")
    content = stream.getvalue()
    with pytest.raises(InvalidUpload):
        validate_file("制度.jpg", content, max_bytes=10000)
    header = struct.pack(">II", 40001, 2000) + content[24:29]
    oversized = (
        content[:16] + header + struct.pack(">I", zlib.crc32(b"IHDR" + header)) + content[33:]
    )
    with pytest.raises(InvalidUpload):
        validate_file("制度.png", oversized, max_bytes=10000)
