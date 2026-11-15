from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KH_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    service_name: str = "enterprise-knowledge-assistant"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://postgres:12345678@127.0.0.1:5544/knowledge_assistant"
    )
    redis_url: str = "redis://127.0.0.1:6384/0"
    s3_endpoint: str = "http://127.0.0.1:9014"
    s3_access_key: str = "admin"
    s3_secret_key: SecretStr = SecretStr("12345678")
    s3_bucket: str = "knowledge-assistant"
    s3_region: str = "us-east-1"
    neo4j_uri: str = "bolt://127.0.0.1:7694"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("12345678")
    graph_namespace: str = Field(
        default="enterprise-knowledge-assistant", min_length=1, max_length=100
    )
    graph_batch_size: int = Field(default=5, ge=1, le=8)
    graph_max_units: int = Field(default=100, ge=1, le=200)
    dependency_timeout: int = Field(default=3, ge=1, le=30)
    cors_origins: list[str] = ["http://127.0.0.1:5174", "http://localhost:5174"]
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    original_prefix: str = "originals"
    parsed_prefix: str = "parsed"
    dispatch_on_accept: bool = True
    dispatch_interval: int = Field(default=10, ge=1)
    job_lease_seconds: int = Field(default=120, ge=5)
    import_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_model: str = Field(
        default="not-configured",
        validation_alias=AliasChoices("KH_EMBEDDING_MODEL", "QWEN_EMBEDDING_MODEL"),
    )
    embedding_dimension: int = Field(
        default=1024,
        gt=0,
        validation_alias=AliasChoices("KH_EMBEDDING_DIMENSION", "QWEN_EMBEDDING_DIMENSION"),
    )
    llm_provider: Literal["qwen", "monkey"] = "qwen"
    qwen_llm_model: str = Field(
        default="qwen3.8-max-0902",
        validation_alias=AliasChoices("KH_QWEN_LLM_MODEL", "QWEN_LLM_MODEL"),
    )
    qwen_rerank_model: str = Field(
        default="qwen3.7-text-rerank",
        validation_alias=AliasChoices("KH_QWEN_RERANK_MODEL", "QWEN_RERANK_MODEL"),
    )
    qwen_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("KH_QWEN_API_KEY", "QWEN_API_KEY")
    )
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("KH_QWEN_BASE_URL", "QWEN_BASE_URL"),
    )
    monkey_llm_model: str = Field(
        default="", validation_alias=AliasChoices("KH_MONKEY_LLM_MODEL", "MONKEY_LLM_MODEL")
    )
    monkey_base_url: str = Field(
        default="", validation_alias=AliasChoices("KH_MONKEY_BASE_URL", "MONKEY_BASE_URL")
    )
    monkey_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("KH_MONKEY_API_KEY", "MONKEY_API_KEY")
    )
    model_trust_env: bool = False
    tavily_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("KH_TAVILY_API_KEY", "TAVILY_API_KEY")
    )
    tavily_trust_env: bool = True
    tavily_timeout_seconds: int = Field(default=20, ge=3, le=30)
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="LANGSMITH_API_KEY"
    )
    langsmith_project: str = Field(
        default="enterprise-knowledge-assistant", validation_alias="LANGSMITH_PROJECT"
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com", validation_alias="LANGSMITH_ENDPOINT"
    )
    langsmith_trust_env: bool = True
    langsmith_record_content: bool = False
    monkey_model_trust_env: bool | None = None
    model_timeout_seconds: int = Field(default=60, ge=5, le=300)
    embedding_batch_size: int = Field(default=20, ge=1, le=20)
    mineru_api_token: SecretStr = SecretStr("")
    mineru_model: str = "vlm"
    mineru_language: str = "ch"
    mineru_poll_seconds: int = Field(default=10, ge=1, le=300)
    mineru_deadline_seconds: int = Field(default=1800, ge=30, le=86400)
