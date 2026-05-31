from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore[import]
from app.core.config import settings

_client: AsyncIOMotorClient = None


async def connect_db():
    global _client
    _client = AsyncIOMotorClient(settings.MONGODB_URL)


async def close_db():
    global _client
    if _client:
        _client.close()


def get_db():
    return _client[settings.MONGODB_DB_NAME]
