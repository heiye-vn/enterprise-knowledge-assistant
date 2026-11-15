from app.config import Settings
from app.infrastructure import s3_client


class ObjectStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def put(self, key: str, content: bytes, mime_type: str, sha256: str):
        with s3_client(self.settings) as client:
            client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=content,
                ContentType=mime_type,
                Metadata={"sha256": sha256},
            )

    def head(self, key: str):
        with s3_client(self.settings) as client:
            return client.head_object(Bucket=self.settings.s3_bucket, Key=key)

    def read(self, key: str) -> bytes:
        return b"".join(self.iter_bytes(key))

    def iter_bytes(self, key: str, byte_range: str | None = None):
        with s3_client(self.settings) as client:
            options = {"Range": byte_range} if byte_range else {}
            response = client.get_object(Bucket=self.settings.s3_bucket, Key=key, **options)
            body = response["Body"]
            try:
                yield from body.iter_chunks(chunk_size=64 * 1024)
            finally:
                body.close()

    def delete(self, key: str):
        with s3_client(self.settings) as client:
            client.delete_object(Bucket=self.settings.s3_bucket, Key=key)

    def list_originals(self):
        yield from self.list_objects(self.settings.original_prefix)

    def list_objects(self, prefix: str):
        with s3_client(self.settings) as client:
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=self.settings.s3_bucket,
                Prefix=prefix.rstrip("/") + "/",
            ):
                for item in page.get("Contents", []):
                    yield {"key": item["Key"], "modified_at": item["LastModified"]}
