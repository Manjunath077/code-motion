import os

import pytest
from unittest.mock import AsyncMock, patch

# Settings requires a key; tests never reach OpenRouter, so any value works.
# Set before anything imports app.core.config.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def no_activity_feed(monkeypatch):
    """Tests never publish to (or read from) a real Redis activity stream."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "ACTIVITY_FEED_ENABLED", False)
    monkeypatch.setattr(settings, "ACTIVITY_CONSOLE_ENABLED", False)


@pytest.fixture(autouse=True)
def mock_db_lifecycle():
    """Prevent real PostgreSQL connections for every test that imports the app."""
    with patch("app.main.connect_db", new_callable=AsyncMock), \
         patch("app.main.close_db", new_callable=AsyncMock):
        yield
