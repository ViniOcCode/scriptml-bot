"""API layer - External infrastructure adapters."""

from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient

__all__ = ["MLApiClient", "CategoryAdapter"]
