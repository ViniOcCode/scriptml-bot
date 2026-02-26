"""Internal schema primitives for migration flows."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

from .helpers import parse_version_parts

logger = logging.getLogger(__name__)


class FieldType(Enum):
    """Tipos de campos suportados no schema."""

    STRING = auto()
    INTEGER = auto()
    DECIMAL = auto()
    BOOLEAN = auto()
    DATE = auto()
    DATETIME = auto()
    LIST = auto()
    JSON = auto()

    def validate(self, value: Any) -> bool:
        """Valida se um valor corresponde ao tipo."""
        if value is None or value == "":
            return True  # Valores vazios são permitidos

        validators = {
            FieldType.STRING: lambda x: isinstance(x, (str, int, float)),
            FieldType.INTEGER: lambda x: isinstance(x, int) or (isinstance(x, str) and x.isdigit()),
            FieldType.DECIMAL: lambda x: isinstance(x, (int, float))
            or (isinstance(x, str) and bool(re.match(r"^-?\d+(\.\d+)?$", str(x)))),
            FieldType.BOOLEAN: lambda x: isinstance(x, bool)
            or str(x).lower() in ("true", "false", "1", "0", "yes", "no", "sim", "não"),
            FieldType.DATE: lambda x: isinstance(x, datetime)
            or (isinstance(x, str) and len(x.split("-")) == 3),
            FieldType.DATETIME: lambda x: isinstance(x, datetime)
            or (isinstance(x, str) and "T" in x or " " in x),
            FieldType.LIST: lambda x: isinstance(x, list) or (isinstance(x, str) and "," in x),
            FieldType.JSON: lambda x: True,  # JSON aceita qualquer estrutura
        }

        return validators.get(self, lambda x: False)(value)  # type: ignore[no-untyped-call]

    def cast(self, value: Any) -> Any:
        """Converte um valor para o tipo apropriado."""
        if value is None or value == "":
            return self.default_value()

        try:
            if self == FieldType.STRING:
                return str(value)
            elif self == FieldType.INTEGER:
                return int(float(str(value).replace(",", "")))
            elif self == FieldType.DECIMAL:
                return float(str(value).replace(",", ""))
            elif self == FieldType.BOOLEAN:
                return str(value).lower() in ("true", "1", "yes", "sim")
            elif self == FieldType.DATE:
                if isinstance(value, datetime):
                    return value.date()
                # Tenta parsear data
                for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]:
                    try:
                        return datetime.strptime(str(value), fmt).date()
                    except ValueError:
                        continue
                return None
            elif self == FieldType.DATETIME:
                if isinstance(value, datetime):
                    return value
                # Tenta parsear datetime
                for fmt in [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%Y %H:%M:%S",
                ]:
                    try:
                        return datetime.strptime(str(value), fmt)
                    except ValueError:
                        continue
                return None
            elif self == FieldType.LIST:
                if isinstance(value, list):
                    return value
                return [v.strip() for v in str(value).split(",")]
            elif self == FieldType.JSON:
                import json

                if isinstance(value, dict):
                    return value
                try:
                    return json.loads(str(value))
                except json.JSONDecodeError:
                    return {}
        except (ValueError, TypeError) as e:
            logger.warning(f"Erro ao converter valor '{value}' para {self}: {e}")
            return self.default_value()

        return value

    def default_value(self) -> Any:
        """Retorna o valor padrão para o tipo."""
        defaults = {
            FieldType.STRING: "",
            FieldType.INTEGER: 0,
            FieldType.DECIMAL: 0.0,
            FieldType.BOOLEAN: False,
            FieldType.DATE: None,
            FieldType.DATETIME: None,
            FieldType.LIST: [],
            FieldType.JSON: {},
        }
        return defaults.get(self)


@dataclass
class Field:
    """Definição de um campo no schema."""

    name: str
    field_type: FieldType
    required: bool = False
    default: Any = None
    description: str = ""
    aliases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:  # noqa: D105
        if self.default is None:
            self.default = self.field_type.default_value()

    def normalize_name(self, name: str) -> bool:
        """Verifica se um nome corresponde a este campo (inclui aliases)."""
        name_lower = name.lower().strip()
        candidates = [self.name.lower()] + [a.lower() for a in self.aliases]
        return name_lower in candidates


class Version:
    """Representa e compara versões semânticas."""

    def __init__(self, version_str: str):  # noqa: D107
        self.original = version_str
        self.parts = self._parse(version_str)

    def _parse(self, version_str: str) -> tuple[int, ...]:
        """Parseia string de versão em componentes numéricos."""
        return parse_version_parts(version_str)

    def __str__(self) -> str:  # noqa: D105
        return self.original

    def __repr__(self) -> str:  # noqa: D105
        return f"Version('{self.original}')"

    def __eq__(self, other: object) -> bool:  # noqa: D105
        if not isinstance(other, Version):
            return NotImplemented
        return self.parts == other.parts

    def __lt__(self, other: Version) -> bool:  # noqa: D105
        return self.parts < other.parts

    def __le__(self, other: Version) -> bool:  # noqa: D105
        return self.parts <= other.parts

    def __gt__(self, other: Version) -> bool:  # noqa: D105
        return self.parts > other.parts

    def __ge__(self, other: Version) -> bool:  # noqa: D105
        return self.parts >= other.parts

    def __hash__(self) -> int:  # noqa: D105
        return hash(self.parts)


@dataclass
class SchemaVersion:
    """Define uma versão de schema com seus campos e metadados.

    Attributes:
        version: String de versão (ex: "1.0", "2.0")
        fields: Dicionário de campos (nome -> Field)
        description: Descrição da versão
        created_at: Data de criação da versão
        deprecated_fields: Lista de campos obsoletos (removidos nesta versão)
    """

    version: str
    fields: dict[str, Field]
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    deprecated_fields: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:  # noqa: D105
        self._version = Version(self.version)

    @property
    def version_obj(self) -> Version:
        """Retorna objeto Version para comparações."""
        return self._version

    def get_field_names(self) -> set[str]:
        """Retorna conjunto de nomes de campos."""
        return set(self.fields.keys())

    def get_required_fields(self) -> list[str]:
        """Retorna lista de campos obrigatórios."""
        return [name for name, fld in self.fields.items() if fld.required]

    def has_field(self, name: str) -> bool:
        """Verifica se o schema tem um campo (considera aliases)."""
        return any(fld.normalize_name(name) for fld in self.fields.values())

    def get_field_by_name(self, name: str) -> Field | None:
        """Retorna campo pelo nome ou alias."""
        for fld in self.fields.values():
            if fld.normalize_name(name):
                return fld
        return None

    def validate_data(self, data: dict[str, Any]) -> list[str]:
        """Valida dados contra este schema.

        Returns:
            Lista de erros de validação (vazia se válido)
        """
        errors = []

        # Verifica campos obrigatórios
        for name, required_field in self.fields.items():
            if required_field.required:
                value = data.get(name)
                if value is None or value == "":
                    errors.append(f"Campo obrigatório ausente: {name}")

        # Valida tipos
        for name, value in data.items():
            field_match = self.get_field_by_name(name)
            if field_match and value is not None and not field_match.field_type.validate(value):
                errors.append(
                    f"Tipo inválido para '{name}': "
                    f"esperado {field_match.field_type.name}, "
                    f"recebido {type(value).__name__}"
                )

        return errors


__all__ = ["Field", "FieldType", "SchemaVersion", "Version"]
