from module_agent.shared.database.base import Base
from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.sql import func



class PaperSelectionModel(Base):
    """映射数据库中的持久化记录。"""
    __tablename__ = "paper_selections"
    
    # 关联的运行记录 ID。
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("literature_runs.id", ondelete="CASCADE"),
        primary_key=True,   
    )
    
    # 用户选中的论文 ID。
    selected_paper_ids: Mapped[list[int]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    
    # 用户对代码产物的补充要求。
    code_requirements: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    
    # 用户完成选择的时间。
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
