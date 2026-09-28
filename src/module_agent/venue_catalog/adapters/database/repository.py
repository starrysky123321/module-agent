from sqlalchemy.ext.asyncio import AsyncSession
from module_agent.venue_catalog.domain.models import Venue
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_
from module_agent.venue_catalog.adapters.database.models import (
    VenueAliasModel,
    VenueModel,
)
from module_agent.venue_catalog.domain.models import VenueRanking



class SqlAlchemyVenueRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session

    async def get_by_name(self, name: str) -> Venue | None:
        # SQLAlchemy 查询
        """获取对应记录。"""
        normalized_name = " ".join(name.casefold().split())
        
        statement = (
            select(VenueModel)
            .outerjoin(VenueModel.aliases)
            .where(
                or_(
                    VenueModel.normalized_name == normalized_name,
                    VenueAliasModel.normalized_alias == normalized_name,
                )
            )
            .options(
                selectinload(VenueModel.aliases),
                selectinload(VenueModel.rankings),
            )
        )

        result = await self.session.execute(statement)

        venue_models = result.scalars().unique().all()
        canonical_matches = [
            venue_model
            for venue_model in venue_models
            if venue_model.normalized_name == normalized_name
        ]

        if len(canonical_matches) == 1:
            venue_model = canonical_matches[0]
        elif len(venue_models) == 1:
            venue_model = venue_models[0]
        else:
            return None
        
        
        return Venue(
            id=venue_model.id,
            canonical_name=venue_model.canonical_name,
            venue_type=venue_model.venue_type,
            aliases=[alias.alias for alias in venue_model.aliases],
            rankings=[
                VenueRanking(
                    ranking_system=ranking.ranking_system,
                    level=ranking.level,
                    edition_year=ranking.edition_year,
                    category=ranking.category,
                    source_url=ranking.source_url,
                )
                for ranking in venue_model.rankings
            ],
        )

        
    
