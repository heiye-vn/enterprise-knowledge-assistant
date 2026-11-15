from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError


class InvalidUpload(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    format: str
    mime_type: str


def validate_file(filename: str, content: bytes, *, max_bytes: int) -> ValidatedFile:
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or len(filename) > 500 or any(ord(c) < 32 for c in filename):
        raise InvalidUpload("文件名无效")
    if not content or len(content) > max_bytes:
        raise InvalidUpload("请选择非空且不超过 20 MB 的文件")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension == "pdf":
        if not content.startswith(b"%PDF-"):
            raise InvalidUpload("文件内容不是有效的 PDF 原件")
        mime = "application/pdf"
    elif extension == "docx":
        try:
            with ZipFile(BytesIO(content)) as package:
                names = set(package.namelist())
                if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                    raise InvalidUpload("文件内容不是 DOCX 文档")
        except BadZipFile:
            raise InvalidUpload("文件内容不是有效的 DOCX 文档") from None
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif extension == "md":
        try:
            value = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise InvalidUpload("Markdown 文件需要使用 UTF-8 编码") from None
        if not value.strip() or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
            raise InvalidUpload("Markdown 文件需要包含可读文本")
        mime = "text/markdown; charset=utf-8"
    elif extension in {"png", "jpg", "jpeg"}:
        expected = "PNG" if extension == "png" else "JPEG"
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format != expected or image.width * image.height > 40_000_000:
                    raise InvalidUpload("图片格式不匹配或超过 4000 万像素限制")
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
            raise InvalidUpload("文件内容不是有效的 PNG 或 JPEG 图片") from None
        extension = "png" if expected == "PNG" else "jpg"
        mime = "image/png" if expected == "PNG" else "image/jpeg"
    else:
        raise InvalidUpload("仅支持 PDF、DOCX、Markdown、PNG 和 JPG/JPEG 文件")
    return ValidatedFile(filename, extension, mime)
