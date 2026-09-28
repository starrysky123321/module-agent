from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class PaperSelection(BaseModel):
    """表示用户确认的选择结果。"""
    # 关联的运行记录 ID。
    run_id: int = Field(gt=0)
    # 用户选中的论文 ID。
    selected_paper_ids: list[int]
    # 用户对代码产物的补充要求。
    code_requirements: str | None = None
    # 用户完成选择的时间。
    selected_at: datetime | None = None
    
    
    @field_validator("selected_paper_ids")
    @classmethod
    def validate_paper_ids(cls, v: list[int]) -> list[int]:
        """校验输入和业务约束。"""
        if len(v) == 0:
            raise ValueError("Selected paper ids cannot be empty")
        if len(set(v)) != len(v):
            raise ValueError("Selected paper ids cannot be duplicate")  
        if any(paper_id <= 0 for paper_id in v):
            raise ValueError("Selected paper ids must be positive")
        return v
