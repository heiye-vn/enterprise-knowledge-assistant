from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KH_", env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    service_name: str = "enterprise-knowledge-assistant"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://knowledge:local-development-password@127.0.0.1:5544/knowledge_assistant"
    )
    redis_url: str = "redis://127.0.0.1:6384/0"
    s3_endpoint: str = "http://127.0.0.1:9014"
    s3_access_key: str = "knowledge-local"
    s3_secret_key: SecretStr = SecretStr("local-development-storage-password")
    s3_bucket: str = "knowledge-assistant"
    s3_region: str = "us-east-1"
    neo4j_uri: str = "bolt://127.0.0.1:7694"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("local-development-graph-password")
    dependency_timeout: int = Field(default=3, ge=1, le=30)
    cors_origins: list[str] = ["http://127.0.0.1:5174", "http://localhost:5174"]
