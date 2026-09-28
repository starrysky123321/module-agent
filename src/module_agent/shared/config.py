from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pathlib import Path
from urllib.parse import unquote, urlsplit



class AppSettings(BaseSettings):
    """封装 AppSettings 相关的数据和行为。"""
    # 应用名称。
    app_name: str = "module-agent"
    # 应用当前运行环境。
    app_env: str = "development"
    # 所有 HTTP 接口的统一前缀。
    api_prefix: str = "/api"
    # 生产 API 使用的 Bearer Token。
    api_auth_token: str = ""
    # 启用的文献检索来源。
    literature_sources: list[str] = Field(default_factory=lambda: ["openalex"])
    # 论文相关性评分器的实现模式。
    literature_relevance_scorer: Literal["rule", "qwen"] = "rule"
    # 论文方法提取器的实现模式。
    literature_method_extractor: Literal["off", "qwen"] = "off"
    
    # OpenAlex API 密钥。
    openalex_api_key: str = ""
    # PostgreSQL 异步连接地址。
    database_url: str = ""
    # Redis 连接地址。
    redis_url: str = ""
    # RabbitMQ 连接地址。
    rabbitmq_url: str = ""
    # Semantic Scholar API 密钥。
    semantic_scholar_api_key: str = ""
    # Semantic Scholar 熔断前允许的连续失败次数。
    semantic_scholar_circuit_failure_threshold: int = 1
    # Semantic Scholar 熔断恢复等待秒数。
    semantic_scholar_circuit_recovery_seconds: float = 60.0

    # GitHub API Token。
    github_token: str = ""
    # GitHub API 基础地址。
    github_api_url: str = "https://api.github.com"
    # GitHub REST API 版本。
    github_api_version: str = "2022-11-28"
    # GitHub 请求超时时间，单位为秒。
    github_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    
    # Qwen API 密钥。
    qwen_api_key: str = ""
    # Qwen API 基础地址。
    qwen_base_url: str = ""
    # Qwen 模型名称。
    qwen_model: str = "qwen3.7-plus"
    # 单次 Qwen 调用超时时间，单位为秒。
    qwen_call_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    
    # LangGraph checkpoint 数据库地址。
    langgraph_database_url: str = ""
    
    # 文献检索词规划器的实现模式。
    literature_query_planner: Literal["rule", "qwen"] = "rule"

    # Code Agent 工作区根目录。
    code_workspace_root: Path = Path("./data/code-workspaces")
    
    # Supervisor 当前启用的决策策略。
    supervisor_policy: Literal[
        "rule",
        "jev_shadow",
        "jev_guarded",
    ] = "rule"

    # Jev 服务使用的 API 密钥。
    typesafe_api_key: str = ""
    # Jev 服务使用的模型名称。
    typesafe_model: str = "jev-latest"
    # 单次 Jev 调用超时时间，单位为秒。
    typesafe_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=30,
    )

    # 允许应用 Jev 建议的最低可信度。
    jev_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )
    # 评估 Jev 前要求的最少观察数。
    jev_readiness_minimum_observations: int = Field(
        default=100,
        ge=1,
    )
    # 评估 Jev 前要求的最低调用成功率。
    jev_readiness_minimum_success_rate: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
    )
    
    
    # 允许获取仓库的最低可信度。
    code_repository_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
    )

    # 每篇论文最多搜索的仓库数量。
    code_repository_search_limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    # 单篇论文 PDF 允许下载的最大字节数。
    code_pdf_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        le=200 * 1024 * 1024,
    )
    # PDF 和论文页面发现请求的超时时间。
    code_pdf_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
    )
    # 论文落地页和补充材料页面的最大响应大小。
    code_landing_page_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )

    # Git 浅克隆超时时间，单位为秒。
    git_clone_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        le=1800,
    )

    # 沙箱验证使用的固定镜像。
    validation_sandbox_image: str = ""
    # 验证阶段读取 Git 信息的超时时间。
    validation_git_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=120,
    )
    # 总工作流超时时间，单位为秒。
    workflow_timeout_seconds: int = Field(
        default=3600,
        ge=1,
        le=86400,
    )



    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


app_settings = AppSettings()


def validate_runtime_security(settings: AppSettings) -> None:
    """Reject common unsafe production configuration mistakes."""

    if settings.app_env.lower() != "production":
        return

    required_urls = {
        "DATABASE_URL": settings.database_url,
        "RABBITMQ_URL": settings.rabbitmq_url,
        "LANGGRAPH_DATABASE_URL": settings.langgraph_database_url,
    }
    missing = [name for name, value in required_urls.items() if not value]
    if missing:
        raise RuntimeError(
            "Production configuration is missing: " + ", ".join(missing)
        )

    unsafe_passwords = {
        "module_agent_dev",
        "password",
        "postgres",
        "changeme",
    }
    for name, value in required_urls.items():
        password = urlsplit(value).password
        if password and unquote(password).lower() in unsafe_passwords:
            raise RuntimeError(
                f"{name} uses a known development password"
            )

    qwen_enabled = any(
        mode == "qwen"
        for mode in (
            settings.literature_query_planner,
            settings.literature_relevance_scorer,
            settings.literature_method_extractor,
        )
    )
    if qwen_enabled and not settings.qwen_api_key.strip():
        raise RuntimeError(
            "QWEN_API_KEY is required when a Qwen component is enabled"
        )

    if (
        settings.supervisor_policy != "rule"
        and not settings.typesafe_api_key.strip()
    ):
        raise RuntimeError(
            "TYPESAFE_API_KEY is required for the configured supervisor"
        )

    if not settings.code_workspace_root.is_absolute():
        raise RuntimeError(
            "CODE_WORKSPACE_ROOT must be absolute in production"
        )

    if len(settings.api_auth_token.strip()) < 32:
        raise RuntimeError(
            "API_AUTH_TOKEN must contain at least 32 characters in production"
        )

    if settings.validation_sandbox_image.endswith(":latest"):
        raise RuntimeError(
            "VALIDATION_SANDBOX_IMAGE must not use the latest tag"
        )
