"""Extended validators for Mercado Livre products."""

import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

from .base import ValidationResult, ValidationSeverity


class ExtendedValidator(ABC):
    """Base abstract class for extended validators."""

    @abstractmethod
    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate data.

        Args:
            data: Data to be validated.

        Returns:
            List of validation results.
        """
        ...


class PriceValidator(ExtendedValidator):
    """Price validator to prevent invalid or suspicious values."""

    ABSOLUTE_MAX_PRICE = 100_000_000.0
    MIN_ACCEPTABLE_PRICE = 0.50
    SUSPICIOUS_PRICES = [0.01, 0.10, 0.99, 1.00, 9.99, 10.00, 99.99, 100.00]
    TEST_PRICES = [0.01, 0.99, 1.11, 9.99, 11.11, 22.22, 33.33, 99.99]

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate product price."""
        results: list[ValidationResult] = []
        price = data.get("price")

        if price is None:
            return results

        try:
            price_float = float(price)
        except (ValueError, TypeError):
            results.append(
                ValidationResult(
                    field="price",
                    message="Preço deve ser um número válido",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        if price_float < 0:
            results.append(
                ValidationResult(
                    field="price",
                    message=f"Preço não pode ser negativo: R$ {price_float:.2f}",
                    severity=ValidationSeverity.ERROR,
                )
            )

        if price_float == 0:
            results.append(
                ValidationResult(
                    field="price",
                    message="Preço não pode ser zero",
                    severity=ValidationSeverity.ERROR,
                )
            )

        if 0 < price_float < self.MIN_ACCEPTABLE_PRICE:
            results.append(
                ValidationResult(
                    field="price",
                    message=f"Preço suspeitamente baixo: R$ {price_float:.2f}",
                    severity=ValidationSeverity.WARNING,
                )
            )

        if price_float > self.ABSOLUTE_MAX_PRICE:
            results.append(
                ValidationResult(
                    field="price",
                    message=f"Preço muito alto: R$ {price_float:,.2f}",
                    severity=ValidationSeverity.ERROR,
                )
            )

        if price_float in self.SUSPICIOUS_PRICES:
            results.append(
                ValidationResult(
                    field="price",
                    message=f"Preço 'chamativo' suspeito: R$ {price_float:.2f}",
                    severity=ValidationSeverity.WARNING,
                )
            )

        return results


class TitleValidator(ExtendedValidator):
    """Title validator with size rules and forbidden words."""

    MIN_TITLE_LENGTH = 5
    MAX_TITLE_LENGTH = 60
    IDEAL_MIN_LENGTH = 15
    IDEAL_MAX_LENGTH = 55

    FORBIDDEN_WORDS = [
        "urgente",
        "promocao",
        "promo",
        "liquidacao",
        "queima de estoque",
        "imperdivel",
        "ultimas unidades",
        "nao perca",
        "compre ja",
        "oferta especial",
        "replica",
        "copia",
        "pirata",
        "generico",
        "mercado livre",
        "frete gratis",
        "parcelado",
        "whatsapp",
        "telefone",
        "ligue",
        "contato",
    ]

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate product title."""
        results: list[ValidationResult] = []
        title = data.get("title", "")

        if not isinstance(title, str):
            results.append(
                ValidationResult(
                    field="title",
                    message="Título deve ser uma string",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        title_lower = title.lower().strip()

        if len(title) < self.MIN_TITLE_LENGTH:
            results.append(
                ValidationResult(
                    field="title",
                    message=(
                        f"Título muito curto: {len(title)} caracteres"
                        f" (mínimo: {self.MIN_TITLE_LENGTH})"
                    ),
                    severity=ValidationSeverity.ERROR,
                )
            )

        if len(title) > self.MAX_TITLE_LENGTH:
            results.append(
                ValidationResult(
                    field="title",
                    message=(
                        f"Título excede o limite: {len(title)} caracteres"
                        f" (máximo: {self.MAX_TITLE_LENGTH})"
                    ),
                    severity=ValidationSeverity.ERROR,
                )
            )

        for word in self.FORBIDDEN_WORDS:
            if word in title_lower:
                results.append(
                    ValidationResult(
                        field="title",
                        message=f"Título contém palavra proibida: '{word}'",
                        severity=ValidationSeverity.ERROR,
                    )
                )

        if title != title.strip():
            results.append(
                ValidationResult(
                    field="title",
                    message="Título contém espaços no início ou fim",
                    severity=ValidationSeverity.WARNING,
                )
            )

        return results


class ImageValidator(ExtendedValidator):
    """Image URL validator."""

    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    ALLOWED_SCHEMES = {"http", "https"}

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate image URLs."""
        results: list[ValidationResult] = []
        pictures = data.get("pictures", [])

        if not pictures:
            results.append(
                ValidationResult(
                    field="pictures",
                    message="Produto deve ter pelo menos uma imagem",
                    severity=ValidationSeverity.WARNING,
                )
            )
            return results

        if len(pictures) > 12:
            results.append(
                ValidationResult(
                    field="pictures",
                    message=(
                        "Produto não pode ter mais que 12 imagens" f" (encontrado: {len(pictures)})"
                    ),
                    severity=ValidationSeverity.ERROR,
                )
            )

        for idx, picture in enumerate(pictures):
            url = None
            if isinstance(picture, str):
                url = picture
            elif isinstance(picture, dict):
                url = picture.get("source") or picture.get("url")

            if not url:
                results.append(
                    ValidationResult(
                        field=f"pictures[{idx}]",
                        message="Imagem sem URL válida",
                        severity=ValidationSeverity.ERROR,
                    )
                )
                continue

            results.extend(self._validate_image_url(url, f"pictures[{idx}]"))

        return results

    def _validate_image_url(self, url: str, field_name: str) -> list[ValidationResult]:
        """Validate a single image URL."""
        results: list[ValidationResult] = []

        try:
            parsed = urlparse(url)
        except Exception:
            results.append(
                ValidationResult(
                    field=field_name,
                    message=f"URL de imagem inválida: {url[:50]}...",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        if not parsed.scheme:
            results.append(
                ValidationResult(
                    field=field_name,
                    message="URL de imagem sem protocolo",
                    severity=ValidationSeverity.ERROR,
                )
            )
        elif parsed.scheme not in self.ALLOWED_SCHEMES:
            results.append(
                ValidationResult(
                    field=field_name,
                    message=f"Protocolo não permitido: '{parsed.scheme}'",
                    severity=ValidationSeverity.ERROR,
                )
            )

        path = parsed.path.lower()
        has_allowed_ext = any(path.endswith(ext) for ext in self.ALLOWED_EXTENSIONS)

        if not has_allowed_ext:
            results.append(
                ValidationResult(
                    field=field_name,
                    message=f"Extensão não permitida. Use: {', '.join(self.ALLOWED_EXTENSIONS)}",
                    severity=ValidationSeverity.ERROR,
                )
            )

        return results


class CategoryValidator(ExtendedValidator):
    """Category validator."""

    CATEGORY_ID_PATTERN = re.compile(r"^[A-Z]{3}\d+$")

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate product category."""
        results: list[ValidationResult] = []
        category_id = data.get("category_id")

        if not category_id:
            results.append(
                ValidationResult(
                    field="category_id",
                    message="Categoria é obrigatória",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        if not isinstance(category_id, str):
            results.append(
                ValidationResult(
                    field="category_id",
                    message="ID de categoria deve ser uma string",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        category_id = category_id.strip()

        if not self.CATEGORY_ID_PATTERN.match(category_id):
            results.append(
                ValidationResult(
                    field="category_id",
                    message=f"Formato inválido: '{category_id}' (esperado: AAA12345)",
                    severity=ValidationSeverity.ERROR,
                )
            )

        return results


class StockValidator(ExtendedValidator):
    """Stock quantity validator."""

    MAX_QUANTITY = 9999

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Validate stock quantity."""
        results: list[ValidationResult] = []
        quantity = data.get("available_quantity")

        if quantity is None:
            results.append(
                ValidationResult(
                    field="available_quantity",
                    message="Quantidade disponível é obrigatória",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        try:
            qty_int = int(quantity)
        except (ValueError, TypeError):
            results.append(
                ValidationResult(
                    field="available_quantity",
                    message="Quantidade deve ser um número inteiro válido",
                    severity=ValidationSeverity.ERROR,
                )
            )
            return results

        if qty_int < 0:
            results.append(
                ValidationResult(
                    field="available_quantity",
                    message=f"Quantidade não pode ser negativa: {qty_int}",
                    severity=ValidationSeverity.ERROR,
                )
            )

        if qty_int == 0:
            results.append(
                ValidationResult(
                    field="available_quantity",
                    message="Produto sem estoque disponível",
                    severity=ValidationSeverity.WARNING,
                )
            )

        if qty_int > self.MAX_QUANTITY:
            results.append(
                ValidationResult(
                    field="available_quantity",
                    message=f"Quantidade excede o limite: {qty_int} (máximo: {self.MAX_QUANTITY})",
                    severity=ValidationSeverity.ERROR,
                )
            )

        return results


class ExtendedValidationSuite:
    """Complete extended validation suite."""

    def __init__(self):  # type: ignore[no-untyped-def]
        """Initialize validation suite."""
        self.validators: list[ExtendedValidator] = [
            PriceValidator(),
            TitleValidator(),
            ImageValidator(),
            CategoryValidator(),
            StockValidator(),
        ]

    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Run all extended validations."""
        all_results: list[ValidationResult] = []

        for validator in self.validators:
            all_results.extend(validator.validate(data))

        return all_results

    def has_errors(self, data: dict[str, Any]) -> bool:
        """Check if there are errors."""
        results = self.validate(data)
        return any(r.is_error() for r in results)

    def get_errors(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Return only errors."""
        results = self.validate(data)
        return [r for r in results if r.is_error()]

    def get_warnings(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Return only warnings."""
        results = self.validate(data)
        return [r for r in results if r.is_warning()]
