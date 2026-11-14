import logging
from collections.abc import Callable
from contextlib import contextmanager

import boto3
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from botocore.config import Config
from neo4j import GraphDatabase
from redis import Redis
from sqlalchemy import text

from app.config import PROJECT_ROOT, Settings
from app.db import create_db_engine

logger = logging.getLogger(__name__)


@contextmanager
def s3_client(settings: Settings):
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=settings.dependency_timeout,
            read_timeout=settings.dependency_timeout,
            retries={"max_attempts": 0},
        ),
    )
    try:
        yield client
    finally:
        client.close()


class DependencyProbe:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _postgres(self):
        engine = create_db_engine(self.settings)
        try:
            with engine.connect() as conn:
                # Readiness includes the applied schema, not just an open TCP port.
                conn.execute(text("SELECT id FROM documents LIMIT 1"))
                if not conn.scalar(
                    text("SELECT count(*) FROM pg_extension WHERE extname='vector'")
                ):
                    raise RuntimeError("pgvector is not installed")
                expected = ScriptDirectory.from_config(
                    AlembicConfig(str(PROJECT_ROOT / "backend/alembic.ini"))
                ).get_heads()
                applied = set(conn.scalars(text("SELECT version_num FROM alembic_version")))
                if applied != set(expected):
                    raise RuntimeError("Database migrations are not current")
        finally:
            engine.dispose()

    def _redis(self):
        with Redis.from_url(
            self.settings.redis_url,
            socket_connect_timeout=self.settings.dependency_timeout,
            socket_timeout=self.settings.dependency_timeout,
        ) as client:
            if not client.ping():
                raise RuntimeError("Redis did not acknowledge PING")

    def _rustfs(self):
        with s3_client(self.settings) as client:
            client.head_bucket(Bucket=self.settings.s3_bucket)

    def _neo4j(self):
        with GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password.get_secret_value()),
            connection_timeout=self.settings.dependency_timeout,
            connection_acquisition_timeout=self.settings.dependency_timeout,
        ) as driver:
            driver.verify_connectivity()

    def check(self) -> dict[str, bool]:
        result = {}
        checks: dict[str, Callable] = {
            "postgres": self._postgres,
            "redis": self._redis,
            "rustfs": self._rustfs,
            "neo4j": self._neo4j,
        }
        for name, check in checks.items():
            try:
                check()
                result[name] = True
            except Exception as error:
                # Driver errors can contain URLs/passwords; expose only the dependency and class.
                logger.warning("Dependency %s unavailable (%s)", name, type(error).__name__)
                result[name] = False
        return result
