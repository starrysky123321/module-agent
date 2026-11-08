"""用于异常、警告与日志的脱敏，不修改用户论文内容。"""

import re
import sys


def redact_sensitive_text(value: str) -> str:
    """隐藏配置密钥、URL 凭据和常见 Token 表达式，保留诊断上下文。"""
    settings = getattr(
        sys.modules.get("module_agent.shared.config"), "app_settings", None
    )
    for name in (
        "api_auth_token",
        "qwen_api_key",
        "openalex_api_key",
        "semantic_scholar_api_key",
        "github_token",
        "typesafe_api_key",
    ):
        secret = getattr(settings, name, "")
        if isinstance(secret, str) and len(secret) >= 8:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"(?i)(\b(?:api[_-]?key|access[_-]?token|token|password|secret)\s*[=:]\s*[\"']?)[^\s&\"'<>]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", value)
    return re.sub(
        r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@",
        r"\1[REDACTED]@",
        value,
        flags=re.I,
    )
