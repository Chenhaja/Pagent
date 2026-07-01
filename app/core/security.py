import re

from app.core.config import Settings


DEFAULT_REDACTION_MAX_LENGTH = 205


def redact_sensitive_text(text: str, max_length: int = DEFAULT_REDACTION_MAX_LENGTH) -> str:
    """脱敏并截断敏感文本。

    Args:
        text: 需要脱敏的原始文本。
        max_length: 脱敏后保留的最大长度。

    Returns:
        隐藏密钥、令牌、密码等敏感内容并按长度截断后的文本。
    """
    redacted = str(text)
    patterns = [
        r"sk-[A-Za-z0-9_-]+",
        r"Bearer\s+[^\s,;]+",
        r"(?i)(password\s*=\s*)[^\s,;]+",
        r"(?i)(token\s*=\s*)[^\s,;]+",
        r"(?i)(api_key\s*=\s*)[^\s,;]+",
    ]
    for pattern in patterns:
        redacted = re.sub(pattern, _redact_match, redacted)
    if len(redacted) > max_length:
        return f"{redacted[:max_length]}...[TRUNCATED]"
    return redacted


def _redact_match(match: re.Match[str]) -> str:
    """保留键名前缀并替换敏感值。"""
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def should_send_full_content(settings: Settings, user_explicitly_allowed: bool) -> bool:
    """判断是否允许向云模型发送完整敏感内容。

    Args:
        settings: 当前应用配置。
        user_explicitly_allowed: 用户是否对本次完整内容外发作出显式允许。

    Returns:
        只有配置允许且用户显式允许时返回 True。
    """
    return settings.allow_cloud_sensitive_content and user_explicitly_allowed
