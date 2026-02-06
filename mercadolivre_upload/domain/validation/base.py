"""Validadores base para produtos do Mercado Livre."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol


class ValidationSeverity(Enum):
    """Severidade de uma validação."""

    ERROR = auto()
    WARNING = auto()
    INFO = auto()


@dataclass
class ValidationResult:
    """Resultado de uma validação."""

    field: str
    message: str
    severity: ValidationSeverity

    def is_error(self) -> bool:
        """Verifica se é um erro."""
        return self.severity == ValidationSeverity.ERROR

    def is_warning(self) -> bool:
        """Verifica se é um aviso."""
        return self.severity == ValidationSeverity.WARNING


class ValidationRule(Protocol):
    """Protocolo para regras de validação."""

    def validate(self, data: dict[str, Any]) -> ValidationResult | None:
        """Valida os dados."""
        ...


class BaseValidator(ABC):
    """Validador base abstrato."""

    def __init__(self):
        """Inicializa o validador."""
        self._rules: list[ValidationRule] = []
        self._errors: list[ValidationResult] = []
        self._warnings: list[ValidationResult] = []

    @abstractmethod
    def validate(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Valida os dados completos.

        Args:
            data: Dados a serem validados.

        Returns:
            Lista de resultados de validação.
        """
        ...

    def add_rule(self, rule: ValidationRule) -> None:
        """Adiciona uma regra de validação.

        Args:
            rule: Regra a ser adicionada.
        """
        self._rules.append(rule)

    def clear_rules(self) -> None:
        """Remove todas as regras."""
        self._rules.clear()

    def has_errors(self) -> bool:
        """Verifica se há erros."""
        return any(r.is_error() for r in self._errors)

    def has_warnings(self) -> bool:
        """Verifica se há avisos."""
        return any(r.is_warning() for r in self._warnings)

    def get_errors(self) -> list[ValidationResult]:
        """Retorna apenas os erros."""
        return [r for r in self._errors if r.is_error()]

    def get_warnings(self) -> list[ValidationResult]:
        """Retorna apenas os avisos."""
        return [r for r in self._warnings if r.is_warning()]

    def _clear_results(self) -> None:
        """Limpa os resultados anteriores."""
        self._errors.clear()
        self._warnings.clear()

    def _apply_rules(self, data: dict[str, Any]) -> list[ValidationResult]:
        """Aplica todas as regras registradas.

        Args:
            data: Dados a serem validados.

        Returns:
            Lista de resultados.
        """
        results: list[ValidationResult] = []

        for rule in self._rules:
            result = rule.validate(data)
            if result:
                results.append(result)
                if result.is_error():
                    self._errors.append(result)
                elif result.is_warning():
                    self._warnings.append(result)

        return results


class RequiredFieldRule:
    """Regra para campos obrigatórios."""

    def __init__(self, field: str, severity: ValidationSeverity = ValidationSeverity.ERROR):
        """Inicializa a regra.

        Args:
            field: Nome do campo obrigatório.
            severity: Severidade da validação.
        """
        self.field = field
        self.severity = severity

    def validate(self, data: dict[str, Any]) -> ValidationResult | None:
        """Valida se o campo está presente e não vazio."""
        value = data.get(self.field)

        if value is None:
            return ValidationResult(
                field=self.field,
                message=f"Campo obrigatório ausente: {self.field}",
                severity=self.severity,
            )

        if isinstance(value, str) and not value.strip():
            return ValidationResult(
                field=self.field,
                message=f"Campo não pode ser vazio: {self.field}",
                severity=self.severity,
            )

        return None


class LengthRule:
    """Regra para validação de tamanho."""

    def __init__(
        self,
        field: str,
        min_length: int | None = None,
        max_length: int | None = None,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
    ):
        """Inicializa a regra.

        Args:
            field: Nome do campo.
            min_length: Tamanho mínimo.
            max_length: Tamanho máximo.
            severity: Severidade da validação.
        """
        self.field = field
        self.min_length = min_length
        self.max_length = max_length
        self.severity = severity

    def validate(self, data: dict[str, Any]) -> ValidationResult | None:
        """Valida o tamanho do campo."""
        value = data.get(self.field)

        if value is None:
            return None

        str_value = str(value)
        length = len(str_value)

        if self.min_length is not None and length < self.min_length:
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ter no mínimo {self.min_length} caracteres",
                severity=self.severity,
            )

        if self.max_length is not None and length > self.max_length:
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ter no máximo {self.max_length} caracteres",
                severity=self.severity,
            )

        return None


class RangeRule:
    """Regra para validação de intervalo numérico."""

    def __init__(
        self,
        field: str,
        min_value: float | None = None,
        max_value: float | None = None,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
    ):
        """Inicializa a regra.

        Args:
            field: Nome do campo.
            min_value: Valor mínimo.
            max_value: Valor máximo.
            severity: Severidade da validação.
        """
        self.field = field
        self.min_value = min_value
        self.max_value = max_value
        self.severity = severity

    def validate(self, data: dict[str, Any]) -> ValidationResult | None:
        """Valida o intervalo do valor."""
        if self.field not in data:
            return None

        value = data[self.field]

        if value is None:
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ser um número válido",
                severity=self.severity,
            )

        try:
            num_value = float(value)
        except (ValueError, TypeError):
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ser um número válido",
                severity=self.severity,
            )

        if self.min_value is not None and num_value < self.min_value:
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ser no mínimo {self.min_value}",
                severity=self.severity,
            )

        if self.max_value is not None and num_value > self.max_value:
            return ValidationResult(
                field=self.field,
                message=f"{self.field} deve ser no máximo {self.max_value}",
                severity=self.severity,
            )

        return None


def create_validator(rules: list[ValidationRule] | None = None) -> BaseValidator:
    """Factory para criar validadores.

    Args:
        rules: Lista opcional de regras.

    Returns:
        Validador configurado.
    """
    from .product_validator import ProductValidator

    validator = ProductValidator()

    if rules:
        for rule in rules:
            validator.add_rule(rule)

    return validator
