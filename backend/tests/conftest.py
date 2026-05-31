import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def mock_db_lifecycle():
    """Prevent real MongoDB connections for every test that imports the app."""
    with patch("app.main.connect_db", new_callable=AsyncMock), \
         patch("app.main.close_db", new_callable=AsyncMock):
        yield
