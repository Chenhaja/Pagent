from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """应用运行配置。

    Args:
        service_name: 服务名称,用于日志和观测字段。
        environment: 运行环境名称。
        log_level: 日志级别。
        llm_api_key: 可选 LLM API Key,默认不配置。
        external_translation_agent_url: 可选外部翻译 agent 地址,默认不配置。

    Returns:
        应用配置对象。
    """

    service_name: str = "patent-agent"
    environment: str = "local"
    log_level: str = "INFO"
    llm_api_key: str | None = Field(default=None, exclude=True)
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
            "external_translation_agent_url": self.external_translation_agent_url,
        }


@lru_cache
def get_settings() -> Settings:
    """获取应用配置单例。

    Returns:
        默认应用配置对象。
    """
    return Settings()
