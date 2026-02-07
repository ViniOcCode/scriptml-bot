"""Mock API client for testing without real auth."""

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

    def publish_item(self, item_data: dict[str, Any]) -> dict[str, Any]:
        """Simulate publishing."""
        import random

        return {
            "id": f"MLB{random.randint(1000000000, 9999999999)}",  # noqa: S311  # noqa: S311
            "status": "active",
            "permalink": "https://mercadolivre.com.br/...",
        }
