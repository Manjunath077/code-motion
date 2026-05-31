from pymongo import MongoClient  # type: ignore[import]
from app.core.config import settings

_client: MongoClient = None


def get_sync_db():
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGODB_URL)
    return _client[settings.MONGODB_DB_NAME]
