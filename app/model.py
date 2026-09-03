"""根据环境变量初始化 LangChain ChatModel。"""

import os
from typing import Any

from langchain.chat_models import init_chat_model


def _setting(name: str, default: str = "") -> str:
    """读取并清理一个环境变量。"""
    return os.getenv(name, default).strip()


def init_model() -> Any:
    """按 ``MODEL_PROVIDER`` 和 ``MODEL_NAME`` 初始化聊天模型。

    各模型提供商自己的认证环境变量（例如 ``OPENAI_API_KEY``）仍由对应
    LangChain 集成自动读取；如需统一配置，也可以使用 ``MODEL_API_KEY``
    和 ``MODEL_BASE_URL`` 覆盖传入。
    """
    model_name = _setting("MODEL_NAME")
    if not model_name:
        raise RuntimeError("MODEL_NOT_CONFIGURED: 请在 .env 中配置 MODEL_NAME")

    provider = _setting("MODEL_PROVIDER", "openai").lower()
    if not provider:
        raise RuntimeError("MODEL_PROVIDER_NOT_CONFIGURED: 请在 .env 中配置 MODEL_PROVIDER")

    temperature_text = _setting("MODEL_TEMPERATURE", "0")
    try:
        temperature = float(temperature_text)
    except ValueError as exc:
        raise RuntimeError("MODEL_TEMPERATURE_INVALID: MODEL_TEMPERATURE 必须是数字") from exc

    kwargs: dict[str, Any] = {"temperature": temperature}
    api_key = _setting("MODEL_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    base_url = _setting("MODEL_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url

    try:
        return init_chat_model(
            model=model_name,
            model_provider=provider,
            **kwargs,
        )
    except ImportError as exc:
        raise RuntimeError(
            f"MODEL_PROVIDER_NOT_INSTALLED: 请安装 {provider} 对应的 LangChain 集成包"
        ) from exc
