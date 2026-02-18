"""Mock API client for testing without real auth."""

from secrets import randbelow
from typing import Any


class MockMLApiClient:
    """Mock client that simulates API responses."""

    def __init__(self, auth_manager: Any = None) -> None:  # noqa: D107
        self.auth = auth_manager

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Return mock category."""
        return {
            "id": category_id,
            "name": "Livros Infantis",
            "path_from_root": [{"id": "MLB437616", "name": "Livros"}],
        }

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Return empty technical specs for tests."""
        return {}

    def publish_item(self, item_data: dict[str, Any]) -> dict[str, Any]:
        """Simulate publishing."""
        return {
            "id": f"MLB{1000000000 + randbelow(9000000000)}",
            "status": "active",
            "permalink": "https://mercadolivre.com.br/...",
        }
