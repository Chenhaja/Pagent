import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """应用运行配置。

    Args:
        service_name: 服务名称,用于日志和观测字段。
        environment: 运行环境名称。
        log_level: 日志级别。
        llm_base_url: OpenAI 兼容 LLM 端点地址,默认不配置。
        llm_model: 默认 LLM 模型名称。
        llm_api_key: 可选 LLM API Key,默认不配置。
        llm_temperature: 默认采样温度。
        llm_max_tokens: 默认最大输出 token 数。
        llm_timeout: 默认请求超时时间。
        llm_retry_count: 默认重试次数。
        llm_retry_backoff: 默认重试退避秒数。
        llm_cheap_model: 可选便宜模型档位。
        llm_strong_model: 可选强模型档位。
        allow_cloud_sensitive_content: 是否允许向云模型发送完整敏感内容。
        redaction_enabled: 是否启用默认脱敏。
        external_translation_agent_url: 可选外部翻译 agent 地址,默认不配置。

    Returns:
        应用配置对象。
    """

    service_name: str = "patent-agent"
    environment: str = "local"
    log_level: str = "INFO"
    llm_base_url: str | None = None
    llm_model: str = ""
    llm_api_key: str | None = Field(default=None, exclude=True)
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_timeout: float = 30.0
    llm_retry_count: int = 2
    llm_retry_backoff: float = 0.5
    llm_cheap_model: str | None = None
    llm_strong_model: str | None = None
    allow_cloud_sensitive_content: bool = False
    redaction_enabled: bool = True
    external_translation_agent_url: str | None = None

    def to_public_dict(self) -> dict[str, str | None]:
        """返回不包含敏感字段的公开配置。

        Returns:
            可安全记录或展示的配置字典。
        """
        return {
            "service_name": self.service_name,
            "environment": self.environment,
            "log_level": self.log_level,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_temperature": str(self.llm_temperature),
            "llm_max_tokens": str(self.llm_max_tokens),
            "llm_timeout": str(self.llm_timeout),
            "llm_retry_count": str(self.llm_retry_count),
            "llm_retry_backoff": str(self.llm_retry_backoff),
            "llm_cheap_model": self.llm_cheap_model,
            "llm_strong_model": self.llm_strong_model,
            "allow_cloud_sensitive_content": str(self.allow_cloud_sensitive_content),
            "redaction_enabled": str(self.redaction_enabled),
            "external_translation_agent_url": self.external_translation_agent_url,
        }


def _get_bool_env(name: str, default: bool) -> bool:
    """读取布尔环境变量。

    Args:
        name: 环境变量名称。
        default: 未配置时使用的默认值。

    Returns:
        解析后的布尔值。
    """
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    """获取应用配置单例。

    Returns:
        从环境变量读取后的应用配置对象。
    """
    return Settings(
        service_name=os.getenv("PAGENT_SERVICE_NAME", "patent-agent"),
        environment=os.getenv("PAGENT_ENVIRONMENT", "local"),
        log_level=os.getenv("PAGENT_LOG_LEVEL", "INFO"),
        llm_base_url=os.getenv("PAGENT_LLM_BASE_URL", "https://api.siliconflow.cn/v1/"),
        llm_model=os.getenv("PAGENT_LLM_MODEL", "deepseek-ai/DeepSeek-V4-Pro"),
        llm_api_key=os.getenv("PAGENT_LLM_API_KEY", "sk-nlamgfhoupneiunsuvkximeaoukneikrrkbddsweulwgjplf"),
        llm_temperature=float(os.getenv("PAGENT_LLM_TEMPERATURE", "0.2")),
        llm_max_tokens=int(os.getenv("PAGENT_LLM_MAX_TOKENS", "2048")),
        llm_timeout=float(os.getenv("PAGENT_LLM_TIMEOUT", "30.0")),
        llm_retry_count=int(os.getenv("PAGENT_LLM_RETRY_COUNT", "2")),
        llm_retry_backoff=float(os.getenv("PAGENT_LLM_RETRY_BACKOFF", "0.5")),
        llm_cheap_model=os.getenv("PAGENT_LLM_CHEAP_MODEL"),
        llm_strong_model=os.getenv("PAGENT_LLM_STRONG_MODEL"),
        allow_cloud_sensitive_content=_get_bool_env("PAGENT_ALLOW_CLOUD_SENSITIVE_CONTENT", False),
        redaction_enabled=_get_bool_env("PAGENT_REDACTION_ENABLED", True),
        external_translation_agent_url=os.getenv("PAGENT_EXTERNAL_TRANSLATION_AGENT_URL"),
    )
