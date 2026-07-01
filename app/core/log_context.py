import logging
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
node_name_var: ContextVar[str | None] = ContextVar("node_name", default=None)
task_type_var: ContextVar[str | None] = ContextVar("task_type", default=None)

_CONTEXT_VARS = {
    "request_id": request_id_var,
    "session_id": session_id_var,
    "trace_id": trace_id_var,
    "node_name": node_name_var,
    "task_type": task_type_var,
}


@dataclass(frozen=True)
class LogContextToken:
    """日志上下文回滚令牌。

    Args:
        tokens: 每个已绑定字段对应的 contextvars token。

    Returns:
        可传给 reset_context 的回滚对象。
    """

    tokens: dict[str, Token[str | None]]


def new_request_id() -> str:
    """生成短请求 ID。

    Returns:
        12 位 UUID 十六进制前缀,用于串联一次请求内的日志。
    """
    return uuid.uuid4().hex[:12]


def bind_context(**fields: str | None) -> LogContextToken:
    """绑定日志上下文字段。

    Args:
        **fields: 需要绑定的上下文字段,仅支持 request_id、session_id、trace_id、node_name、task_type。

    Returns:
        可用于 reset_context 的回滚令牌。
    """
    tokens: dict[str, Token[str | None]] = {}
    for key, value in fields.items():
        context_var = _CONTEXT_VARS.get(key)
        if context_var is None:
            continue
        tokens[key] = context_var.set(value)
    return LogContextToken(tokens=tokens)


def reset_context(token: LogContextToken) -> None:
    """回滚日志上下文绑定。

    Args:
        token: bind_context 返回的回滚令牌。

    Returns:
        无返回值。
    """
    for key, var_token in reversed(list(token.tokens.items())):
        context_var = _CONTEXT_VARS.get(key)
        if context_var is not None:
            context_var.reset(var_token)


def current_context() -> dict[str, str | None]:
    """读取当前日志上下文。

    Returns:
        包含 request_id、session_id、trace_id、node_name、task_type 的上下文字典。
    """
    return {key: context_var.get() for key, context_var in _CONTEXT_VARS.items()}


class ContextFilter(logging.Filter):
    """把 contextvars 日志上下文注入 LogRecord。

    Returns:
        logging filter 实例。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """向 LogRecord 写入上下文字段。

        Args:
            record: Python logging 日志记录。

        Returns:
            始终返回 True,允许日志继续输出。
        """
        try:
            for key, value in current_context().items():
                if not hasattr(record, key):
                    setattr(record, key, value)
        except Exception:
            return True
        return True
