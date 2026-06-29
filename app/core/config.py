import os
from functools import lru_cache
from pathlib import Path

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
        memory_enabled: 是否启用会话记忆。
        memory_db_path: 会话记忆 SQLite 数据库路径。
        memory_history_window: 会话记忆保留的最近原文 turn 数。
        memory_token_budget: 触发摘要的字符预算。
        memory_summary_model: 可选摘要模型名称。
        retrieval_backend: 检索后端名称。
        retrieval_top_k: 默认检索召回数量。
        retrieval_max_steps: 检索最大步数。
        retrieval_token_budget: 检索 evidence token 预算。
        retrieval_timeout_seconds: 检索超时时间。
        retrieval_default_status: 默认法规版本状态。
        retrieval_enable_time_filter: 是否启用法规时间过滤。
        law_stale_days: 法规检索时间超过该天数后提示核对。
        qdrant_url: Qdrant 服务地址。
        qdrant_api_key: 可选 Qdrant API Key。
        qdrant_collection: Qdrant 集合名称。
        embedding_base_url: OpenAI 兼容 embedding 端点地址。
        embedding_vector_size: embedding 向量维度。
        embedding_model: embedding 模型名称。
        embedding_api_key: 可选 embedding API Key。

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
    memory_enabled: bool = True
    memory_db_path: str = "./pagent_memory.db"
    memory_history_window: int = 6
    memory_token_budget: int = 1500
    memory_summary_model: str | None = None
    retrieval_backend: str = "qdrant"
    retrieval_top_k: int = 3
    retrieval_max_steps: int = 1
    retrieval_token_budget: int = 1000
    retrieval_timeout_seconds: int = 10
    retrieval_default_status: str = "current"
    retrieval_enable_time_filter: bool = True
    law_stale_days: int = 365
    qdrant_url: str | None = None
    qdrant_api_key: str | None = Field(default=None, exclude=True)
    qdrant_collection: str = "patent_kb"
    embedding_base_url: str | None = None
    embedding_vector_size: int = 1024
    embedding_model: str = ""
    embedding_api_key: str | None = Field(default=None, exclude=True)

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
            "memory_enabled": str(self.memory_enabled),
            "memory_db_path": self.memory_db_path,
            "memory_history_window": str(self.memory_history_window),
            "memory_token_budget": str(self.memory_token_budget),
            "memory_summary_model": self.memory_summary_model,
            "retrieval_backend": self.retrieval_backend,
            "retrieval_top_k": str(self.retrieval_top_k),
            "retrieval_max_steps": str(self.retrieval_max_steps),
            "retrieval_token_budget": str(self.retrieval_token_budget),
            "retrieval_timeout_seconds": str(self.retrieval_timeout_seconds),
            "retrieval_default_status": self.retrieval_default_status,
            "retrieval_enable_time_filter": str(self.retrieval_enable_time_filter),
            "law_stale_days": str(self.law_stale_days),
            "qdrant_url": self.qdrant_url,
            "qdrant_collection": self.qdrant_collection,
            "embedding_base_url": self.embedding_base_url,
            "embedding_vector_size": str(self.embedding_vector_size),
            "embedding_model": self.embedding_model,
        }


def _load_local_dotenv() -> None:
    """读取项目根目录 .env 到当前进程环境变量。

    Returns:
        无返回值;已有环境变量不会被 .env 覆盖。
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    dotenv_paths = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    dotenv_path = next((path for path in dotenv_paths if path.exists()), None)
    if dotenv_path is None:
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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
    _load_local_dotenv()
    return Settings(
        service_name=os.getenv("PAGENT_SERVICE_NAME", "patent-agent"),
        environment=os.getenv("PAGENT_ENVIRONMENT", "local"),
        log_level=os.getenv("PAGENT_LOG_LEVEL", "INFO"),
        llm_base_url=os.getenv("PAGENT_LLM_BASE_URL"),
        llm_model=os.getenv("PAGENT_LLM_MODEL", ""),
        llm_api_key=os.getenv("PAGENT_LLM_API_KEY"),
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
        memory_enabled=_get_bool_env("PAGENT_MEMORY_ENABLED", True),
        memory_db_path=os.getenv("PAGENT_MEMORY_DB_PATH", "./pagent_memory.db"),
        memory_history_window=int(os.getenv("PAGENT_MEMORY_HISTORY_WINDOW", "6")),
        memory_token_budget=int(os.getenv("PAGENT_MEMORY_TOKEN_BUDGET", "1500")),
        memory_summary_model=os.getenv("PAGENT_MEMORY_SUMMARY_MODEL"),
        retrieval_backend=os.getenv("PAGENT_RETRIEVAL_BACKEND", "qdrant"),
        retrieval_top_k=int(os.getenv("PAGENT_RETRIEVAL_TOP_K", "3")),
        retrieval_max_steps=int(os.getenv("PAGENT_RETRIEVAL_MAX_STEPS", "1")),
        retrieval_token_budget=int(os.getenv("PAGENT_RETRIEVAL_TOKEN_BUDGET", "1000")),
        retrieval_timeout_seconds=int(os.getenv("PAGENT_RETRIEVAL_TIMEOUT_SECONDS", "10")),
        retrieval_default_status=os.getenv("PAGENT_RETRIEVAL_DEFAULT_STATUS", "current"),
        retrieval_enable_time_filter=_get_bool_env("PAGENT_RETRIEVAL_ENABLE_TIME_FILTER", True),
        law_stale_days=int(os.getenv("PAGENT_LAW_STALE_DAYS", "365")),
        qdrant_url=os.getenv("PAGENT_QDRANT_URL"),
        qdrant_api_key=os.getenv("PAGENT_QDRANT_API_KEY"),
        qdrant_collection=os.getenv("PAGENT_QDRANT_COLLECTION", "patent_kb"),
        embedding_base_url=os.getenv("PAGENT_EMBEDDING_BASE_URL"),
        embedding_vector_size=int(os.getenv("PAGENT_EMBEDDING_VECTOR_SIZE", "1024")),
        embedding_model=os.getenv("PAGENT_EMBEDDING_MODEL", ""),
        embedding_api_key=os.getenv("PAGENT_EMBEDDING_API_KEY"),
    )
