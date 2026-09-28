from module_agent.literature.domain.method import PaperMethodExtractor
from module_agent.shared.llm.qwen_client import QwenClientManager
from module_agent.literature.adapters.llm.qwen_method_extractor import (
    QwenPaperMethodExtractor,
)
from module_agent.literature.application.method_extraction import (
    BatchedPaperMethodExtractor,
    FallbackPaperMethodExtractor,
)

def build_paper_method_extractor(
    mode: str,
    qwen_model: str,
    qwen_client_manager: QwenClientManager,
    timeout_seconds: float = 180.0,
) -> PaperMethodExtractor | None:
    """构建并返回目标对象。"""
    if mode == "off":
        return None

    if mode == "qwen":
        qwen = QwenPaperMethodExtractor(
            model=qwen_model,
            client=qwen_client_manager.get_client(),
        )

        fallback = FallbackPaperMethodExtractor(
            primary=qwen,
            timeout_seconds=timeout_seconds,
            model=qwen_model,
        )

        return BatchedPaperMethodExtractor(
            inner=fallback,
            batch_size=10,
        )

    raise ValueError(f"Unknown mode: {mode}")
