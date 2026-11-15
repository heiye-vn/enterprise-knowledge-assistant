from pydantic import SecretStr

from app.config import Settings


def test_user_model_variable_names_are_loaded_without_renaming_keys(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "QWEN_LLM_MODEL=qwen3.8-max-0902\n"
        "QWEN_EMBEDDING_MODEL=qwen3.7-text-embedding-flash\n"
        "QWEN_EMBEDDING_DIMENSION=1024\n"
        "QWEN_RERANK_MODEL=qwen3.7-text-rerank\n"
        "QWEN_BASE_URL=https://qwen.test/compatible-mode/v1\n"
        "QWEN_API_KEY=qwen-private-example\n"
        "MONKEY_BASE_URL=https://monkey.test\n"
        "MONKEY_API_KEY=monkey-private-example\n"
        "MONKEY_LLM_MODEL=gpt-6.1-sol\n"
        "KH_LLM_PROVIDER=monkey\n"
    )
    settings = Settings(_env_file=path)
    assert settings.embedding_model == "qwen3.7-text-embedding-flash"
    assert settings.embedding_dimension == 1024
    assert settings.qwen_rerank_model == "qwen3.7-text-rerank"
    assert settings.llm_provider == "monkey"
    assert settings.monkey_llm_model == "gpt-6.1-sol"
    assert isinstance(settings.qwen_api_key, SecretStr)
    assert settings.monkey_api_key.get_secret_value() == "monkey-private-example"
    assert "private-example" not in repr(settings)


def test_existing_kh_embedding_overrides_the_compatible_variable_name(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KH_EMBEDDING_MODEL=explicit-model\nQWEN_EMBEDDING_MODEL=other\n")
    assert Settings(_env_file=path).embedding_model == "explicit-model"


def test_constructor_settings_remain_supported():
    settings = Settings(_env_file=None, embedding_model="chosen", qwen_api_key=SecretStr("private"))
    assert settings.embedding_model == "chosen"
    assert settings.qwen_api_key.get_secret_value() == "private"


def test_model_connection_defaults_to_direct_and_environment_proxy_is_opt_in(tmp_path):
    assert Settings(_env_file=None).model_trust_env is False
    path = tmp_path / ".env"
    path.write_text("KH_MODEL_TRUST_ENV=true\n")
    assert Settings(_env_file=path).model_trust_env is True


def test_third_party_model_can_choose_its_network_path_separately(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KH_MODEL_TRUST_ENV=false\nKH_MONKEY_MODEL_TRUST_ENV=true\n")
    settings = Settings(_env_file=path)
    assert settings.model_trust_env is False
    assert settings.monkey_model_trust_env is True
