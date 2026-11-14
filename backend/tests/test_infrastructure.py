from uuid import uuid4

import pytest
from neo4j import GraphDatabase
from redis import Redis

pytestmark = pytest.mark.integration


def test_actual_dependencies_and_schema_are_ready():
    from app.bootstrap import ensure_bucket
    from app.config import Settings
    from app.infrastructure import DependencyProbe

    settings = Settings()
    ensure_bucket(settings)
    assert DependencyProbe(settings).check() == {
        "postgres": True,
        "redis": True,
        "rustfs": True,
        "neo4j": True,
    }


def test_redis_roundtrip_uses_isolated_key():
    from app.config import Settings

    key = f"foundation-test:{uuid4()}"
    with Redis.from_url(Settings().redis_url) as redis:
        try:
            redis.set(key, "queued", ex=60)
            assert redis.get(key) == b"queued"
        finally:
            redis.delete(key)


def test_rustfs_put_head_range_list_delete():
    from app.bootstrap import ensure_bucket
    from app.config import Settings
    from app.infrastructure import s3_client

    settings = Settings()
    ensure_bucket(settings)
    prefix = f"integration/{uuid4()}/"
    key = prefix + "原文.txt"
    payload = "电子发票原始 PDF，保留完整来源。".encode()
    with s3_client(settings) as s3:
        try:
            s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=payload)
            assert s3.head_object(Bucket=settings.s3_bucket, Key=key)["ContentLength"] == len(
                payload
            )
            with s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"] as body:
                assert body.read() == payload
            response = s3.get_object(Bucket=settings.s3_bucket, Key=key, Range="bytes=0-8")
            with response["Body"] as body:
                assert body.read() == payload[:9]
            assert response["ResponseMetadata"]["HTTPStatusCode"] == 206
            objects = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix)
            assert [item["Key"] for item in objects["Contents"]] == [key]
        finally:
            s3.delete_object(Bucket=settings.s3_bucket, Key=key)
        assert s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix).get("KeyCount", 0) == 0


def test_neo4j_query_roundtrip_is_independent_of_pg():
    from app.config import Settings

    settings = Settings()
    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
    ) as driver:
        records, _, _ = driver.execute_query("RETURN $value AS value", value="图谱连接可用")
        assert records[0]["value"] == "图谱连接可用"
