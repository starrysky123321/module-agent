from redis.asyncio import Redis
from module_agent.shared.config import app_settings


def create_redis_client(redis_url: str) -> Redis:
    
    """创建对应记录。"""
    return Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)


redis_client = create_redis_client(app_settings.redis_url)
