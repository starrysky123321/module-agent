from module_agent.shared.config import app_settings
from openai import AsyncOpenAI

class QwenClientManager:
    """管理外部客户端及其生命周期。"""
    def __init__(self, api_key: str, base_url: str):
        """初始化当前对象。"""
        self._api_key = api_key.strip()
        self._base_url = base_url.strip()
        self._client: AsyncOpenAI | None = None
        
        
    def get_client(self) -> AsyncOpenAI:
        """获取对应记录。"""
        if self._client is None:
            
            if not self._api_key:
                raise RuntimeError("Qwen API key is not configured.")
            if not self._base_url:
                raise RuntimeError("Qwen base URL is not configured.")
            
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client
    
    
    async def close(self) -> None:
        """关闭并释放外部资源。"""
        if self._client is not None:
            await self._client.close()
            self._client = None
            
            

qwen_client_manager = QwenClientManager(
    api_key=app_settings.qwen_api_key,
    base_url=app_settings.qwen_base_url,
)
