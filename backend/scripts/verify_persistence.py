"""Verify all four named volumes across container recreation; remove only our own markers.

Run with `uv run --directory backend python -m scripts.verify_persistence prepare`,
recreate this project's containers, then run again with `verify`.
"""

import argparse
import json
from uuid import UUID, uuid4

from neo4j import GraphDatabase
from redis import Redis
from sqlalchemy import delete

from app.config import PROJECT_ROOT, Settings
from app.db import create_db_engine, session_factory
from app.infrastructure import s3_client
from app.models import Document

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["prepare", "verify"])
args = parser.parse_args()
manifest = PROJECT_ROOT / ".local/persistence-probe.json"
if args.action == "prepare":
    if manifest.exists():
        raise SystemExit("A previous probe exists; verify it before creating another.")
    marker = str(uuid4())
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(json.dumps({"marker": marker}), encoding="utf-8")
else:
    marker = json.loads(manifest.read_text(encoding="utf-8"))["marker"]

settings = Settings()
engine = create_db_engine(settings)
key = f"foundation-probe/{marker}/original.txt"
redis_key = f"foundation-probe:{marker}"
payload = "基础设施持久化验证".encode()
with (
    session_factory(engine)() as db,
    s3_client(settings) as s3,
    Redis.from_url(
        settings.redis_url,
    ) as redis,
    GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
    ) as graph,
):
    if args.action == "prepare":
        db.add(Document(id=UUID(marker), title="基础设施持久化验证（临时）"))
        db.commit()
        s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=payload)
        redis.set(redis_key, payload, ex=3600)
        graph.execute_query(
            "CREATE (n:FoundationProbe {id: $id, value: $value})", id=marker, value="persisted"
        )
        print("Prepared isolated PostgreSQL, Redis, RustFS and Neo4j markers.")
    else:
        assert db.get(Document, UUID(marker)).title == "基础设施持久化验证（临时）"
        assert redis.get(redis_key) == payload
        with s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"] as body:
            assert body.read() == payload
        rows, _, _ = graph.execute_query(
            "MATCH (n:FoundationProbe {id: $id}) RETURN n.value AS value",
            id=marker,
        )
        assert rows[0]["value"] == "persisted"
        db.execute(delete(Document).where(Document.id == UUID(marker)))
        db.commit()
        s3.delete_object(Bucket=settings.s3_bucket, Key=key)
        redis.delete(redis_key)
        graph.execute_query("MATCH (n:FoundationProbe {id: $id}) DELETE n", id=marker)
        manifest.unlink()
        print("PASS: all four services retained data; isolated markers removed.")
engine.dispose()
