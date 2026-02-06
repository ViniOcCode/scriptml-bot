"""Mock API client for testing without real auth."""


class MockMLApiClient:
    """Mock client that simulates API responses."""

    def __init__(self, auth_manager=None):
        self.auth = auth_manager

    def get_category(self, category_id):
        """Return mock category."""
        return {
            "id": category_id,
            "name": "Livros Infantis",
            "path_from_root": [{"id": "MLB437616", "name": "Livros"}],
        }

    def publish_item(self, item_data):
        """Simulate publishing."""
        import random

        return {
            "id": f"MLB{random.randint(1000000000, 9999999999)}",
            "status": "active",
            "permalink": "https://mercadolivre.com.br/...",
        }
