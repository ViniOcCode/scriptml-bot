"""API layer - External infrastructure adapters."""

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.api.category_adapter import CategoryAdapter

__all__ = ["MLApiClient", "CategoryAdapter"]
