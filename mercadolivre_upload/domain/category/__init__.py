"""Category domain module."""

from mercadolivre_upload.domain.category.errors import CategoryApiUnavailableError
from mercadolivre_upload.domain.category.resolver import CategoryApiPort, CategoryResolver

__all__ = ["CategoryResolver", "CategoryApiPort", "CategoryApiUnavailableError"]
