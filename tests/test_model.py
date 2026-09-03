"""模型初始化工厂测试。"""

import pytest

import app.model as model_module


def test_init_model_uses_provider_name_and_generic_options(monkeypatch):
    """模型提供商、名称和通用参数应传给 LangChain 初始化函数。"""
    captured = {}

    def fake_init_chat_model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_module, "init_chat_model", fake_init_chat_model)
    monkeypatch.setenv("MODEL_PROVIDER", "Anthropic")
    monkeypatch.setenv("MODEL_NAME", "claude-3-5-sonnet")
    monkeypatch.setenv("MODEL_TEMPERATURE", "0.25")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://model.example/v1")

    assert model_module.init_model() is not None
    assert captured == {
        "model": "claude-3-5-sonnet",
        "model_provider": "anthropic",
        "temperature": 0.25,
        "api_key": "test-key",
        "base_url": "https://model.example/v1",
    }


def test_init_model_defaults_provider_to_openai(monkeypatch):
    """未设置 MODEL_PROVIDER 时保持 OpenAI 兼容配置的向后兼容。"""
    captured = {}
    monkeypatch.setattr(model_module, "init_chat_model", lambda **kwargs: captured.update(kwargs) or object())
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("MODEL_NAME", "gpt-4o-mini")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_TEMPERATURE", raising=False)

    model_module.init_model()

    assert captured["model_provider"] == "openai"
    assert captured["temperature"] == 0


def test_init_model_rejects_invalid_temperature(monkeypatch):
    """错误的温度配置应在启动调用模型前给出明确错误。"""
    monkeypatch.setenv("MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setenv("MODEL_TEMPERATURE", "not-a-number")

    with pytest.raises(RuntimeError, match="MODEL_TEMPERATURE_INVALID"):
        model_module.init_model()
