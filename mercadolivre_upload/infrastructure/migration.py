"""Sistema de migração e versionamento de schema de dados.

Este módulo fornece ferramentas para versionar estruturas de planilhas,
detectar versões automaticamente e migrar dados entre versões.

Classes principais:
    - SchemaVersion: Define campos e tipos de uma versão de schema
    - Migration: Define como migrar de uma versão para outra
    - MigrationManager: Aplica migrações pendentes

Example:
    >>> from mercadolivre_upload.infrastructure.migration import (
    ...     SchemaVersion, Migration, MigrationManager, FieldType
    ... )
    >>>
    >>> # Define schema v1.0
    >>> v1 = SchemaVersion("1.0", fields={
    ...     "sku": FieldType.STRING,
    ...     "title": FieldType.STRING,
    ...     "price": FieldType.DECIMAL,
    ... })
    >>>
    >>> # Define schema v2.0 (adiciona gtin)
    >>> v2 = SchemaVersion("2.0", fields={
    ...     "sku": FieldType.STRING,
    ...     "title": FieldType.STRING,
    ...     "price": FieldType.DECIMAL,
    ...     "gtin": FieldType.STRING,
    ... })
    >>>
    >>> # Cria migração
    >>> class V1ToV2(Migration):
    ...     def migrate(self, data):
    ...         data["gtin"] = ""
    ...         return data
    >>>
    >>> # Aplica migração
    >>> manager = MigrationManager([v1, v2], [V1ToV2()])
    >>> migrated = manager.migrate_data({"sku": "ABC", "title": "Produto"}, "1.0", "2.0")
"""

from __future__ import annotations

import contextlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, TypeVar

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import openpyxl  # noqa: F401

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


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
        # Remove prefixo 'v' se existir
        version_str = version_str.lstrip("vV")
        # Separa por pontos
        parts = re.split(r"[.-]", version_str)

        result = []
        for part in parts:
            with contextlib.suppress(ValueError):
                result.append(int(part))

        return tuple(result) if result else (0,)

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
        return any(field.normalize_name(name) for fld in self.fields.values())  # type: ignore[attr-defined]

    def get_field_by_name(self, name: str) -> Field | None:
        """Retorna campo pelo nome ou alias."""
        for _fld in self.fields.values():
            if field.normalize_name(name):  # type: ignore[attr-defined]
                return field  # type: ignore[return-value]
        return None

    def validate_data(self, data: dict[str, Any]) -> list[str]:
        """Valida dados contra este schema.

        Returns:
            Lista de erros de validação (vazia se válido)
        """
        errors = []

        # Verifica campos obrigatórios
        for name, _fld in self.fields.items():
            if field.required:  # type: ignore[attr-defined]
                value = data.get(name)
                if value is None or value == "":
                    errors.append(f"Campo obrigatório ausente: {name}")

        # Valida tipos
        for name, value in data.items():
            fld = self.get_field_by_name(name)
            if fld and value is not None and not fld.field_type.validate(value):
                errors.append(
                    f"Tipo inválido para '{name}': "
                    f"esperado {field.field_type.name}, "  # type: ignore[attr-defined]
                    f"recebido {type(value).__name__}"
                )

        return errors


T = TypeVar("T")


class Migration[T](ABC):
    """Classe abstrata para migrações entre versões.

    Subclasses devem implementar o método `migrate` para transformar
    dados da versão source para a versão target.

    Example:
        >>> class V1ToV2(Migration[dict]):
        ...     source_version = "1.0"
        ...     target_version = "2.0"
        ...
        ...     def migrate(self, data: dict) -> dict:
        ...         # Adiciona campo gtin
        ...         data["gtin"] = data.get("gtin", "")
        ...         return data
    """

    source_version: str
    target_version: str
    description: str = ""

    @abstractmethod
    def migrate(self, data: T) -> T:
        """Migra dados da versão source para target.

        Args:
            data: Dados na versão source

        Returns:
            Dados migrados para versão target
        """
        pass

    def can_migrate(self, from_version: str, to_version: str) -> bool:
        """Verifica se esta migração pode ser aplicada."""
        return Version(from_version) == Version(self.source_version) and Version(
            to_version
        ) == Version(self.target_version)

    def applies_to_path(self, from_version: Version, to_version: Version) -> bool:
        """Verifica se esta migração faz parte do caminho entre duas versões."""
        src = Version(self.source_version)
        tgt = Version(self.target_version)
        return src >= from_version and tgt <= to_version and src < tgt


@dataclass
class MigrationResult:
    """Resultado de uma operação de migração."""

    success: bool
    data: Any
    source_version: str
    target_version: str
    applied_migrations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def migration_count(self) -> int:
        """Número de migrações aplicadas."""
        return len(self.applied_migrations)


class MigrationManager:
    """Gerencia schemas e aplica migrações entre versões.

    Responsável por:
    - Registrar versões de schema
    - Registrar migrações
    - Detectar versão de dados automaticamente
    - Aplicar migrações em sequência

    Example:
        >>> manager = MigrationManager()
        >>> manager.register_schema(v1_schema)
        >>> manager.register_schema(v2_schema)
        >>> manager.register_migration(V1ToV2())
        >>>
        >>> # Detecta e migra automaticamente
        >>> result = manager.auto_migrate(data)
        >>> if result.success:
        ...     print(f"Migrado para {result.target_version}")
    """

    def __init__(  # noqa: D107
        self,
        schemas: list[SchemaVersion] | None = None,
        migrations: list[Migration[Any]] | None = None,
        target_version: str | None = None,
    ):
        self.schemas: dict[str, SchemaVersion] = {}
        self.migrations: list[Migration[Any]] = []
        self.target_version = target_version

        if schemas:
            for schema in schemas:
                self.register_schema(schema)

        if migrations:
            for migration in migrations:
                self.register_migration(migration)

    def register_schema(self, schema: SchemaVersion) -> None:
        """Registra uma versão de schema."""
        self.schemas[schema.version] = schema
        logger.debug(f"Schema registrado: {schema.version}")

    def register_migration(self, migration: Migration[Any]) -> None:
        """Registra uma migração."""
        self.migrations.append(migration)
        logger.debug(
            f"Migração registrada: {migration.source_version} -> " f"{migration.target_version}"
        )

    def get_schema(self, version: str) -> SchemaVersion | None:
        """Retorna schema pela versão."""
        return self.schemas.get(version)

    def get_latest_version(self) -> str | None:
        """Retorna a versão mais recente registrada."""
        if not self.schemas:
            return None

        versions = [(Version(v), v) for v in self.schemas]
        versions.sort(reverse=True)
        return versions[0][1] if versions else None

    def detect_version(self, data: dict[str, Any]) -> str | None:
        """Detecta a versão dos dados com base nos campos presentes.

        Algoritmo:
        1. Verifica se há metadado explícito de versão
        2. Compara campos com schemas registrados
        3. Retorna a versão mais específica que corresponde

        Returns:
            Versão detectada ou None se não corresponder a nenhum schema
        """
        # 1. Verifica metadado explícito
        explicit_version = data.get("_schema_version") or data.get("__version")
        if explicit_version and explicit_version in self.schemas:
            return explicit_version  # type: ignore[no-any-return]

        # 2. Compara campos com schemas
        data_fields = set(data.keys())
        best_match: tuple[str, float] | None = None

        for version, schema in self.schemas.items():
            schema_fields = schema.get_field_names()

            # Ignora campos de metadados
            data_fields_clean = {f for f in data_fields if not f.startswith("_")}

            # Calcula score de correspondência
            if schema_fields:
                # Campos em comum
                common = data_fields_clean & schema_fields
                # Campos extras nos dados (não conhecidos por este schema)
                extra = data_fields_clean - schema_fields
                # Campos faltantes (do schema que não estão nos dados)
                missing = schema_fields - data_fields_clean

                # Score: mais campos em comum é melhor
                # Penalidade leve para campos extras
                # Penalidade maior para campos obrigatórios faltantes
                coverage = len(common) / len(schema_fields) if schema_fields else 0
                required_missing = sum(
                    1 for f in missing if schema.fields.get(f) and schema.fields[f].required
                )

                # Penalidades
                extra_penalty = min(len(extra) * 0.05, 0.3)  # Max 0.3 de penalidade
                missing_penalty = required_missing * 0.3

                score = coverage - extra_penalty - missing_penalty

                # Bônus para schemas que cobrem mais campos dos dados
                if data_fields_clean:
                    field_match_ratio = len(common) / len(data_fields_clean)
                    score += field_match_ratio * 0.1

                if best_match is None or score > best_match[1]:
                    best_match = (version, score)

        # Retorna apenas se score é razoável (> 0.2)
        if best_match and best_match[1] > 0.2:
            return best_match[0]

        return None

    def find_migration_path(
        self,
        from_version: str,
        to_version: str,
    ) -> list[Migration[Any]]:
        """Encontra sequência de migrações para ir de A para B.

        Uses BFS (Breadth-First Search) para encontrar o caminho mais curto.

        Returns:
            Lista ordenada de migrações a aplicar
        """
        if from_version == to_version:
            return []

        from_v = Version(from_version)
        to_v = Version(to_version)

        if from_v > to_v:
            raise ValueError(
                f"Não é possível migrar de {from_version} para {to_version} "
                "(downgrade não suportado)"
            )

        # BFS para encontrar caminho
        from collections import deque

        queue: deque[tuple[Version, list[Migration[Any]]]] = deque([(from_v, [])])
        visited: set[Version] = {from_v}

        while queue:
            current, path = queue.popleft()

            if current == to_v:
                return path

            # Encontra migrações possíveis a partir da versão atual
            for migration in self.migrations:
                migration_src = Version(migration.source_version)
                migration_tgt = Version(migration.target_version)

                if migration_src == current and migration_tgt not in visited:
                    visited.add(migration_tgt)
                    queue.append((migration_tgt, path + [migration]))

        raise ValueError(
            f"Não foi encontrado caminho de migração de {from_version} " f"para {to_version}"
        )

    def migrate_data(
        self,
        data: T,
        from_version: str,
        to_version: str,
    ) -> MigrationResult:
        """Migra dados de uma versão para outra.

        Args:
            data: Dados a serem migrados
            from_version: Versão atual dos dados
            to_version: Versão desejada

        Returns:
            Resultado da migração com dados migrados e metadados
        """
        result = MigrationResult(
            success=False,
            data=data,
            source_version=from_version,
            target_version=to_version,
        )

        try:
            # Encontra caminho de migração
            path = self.find_migration_path(from_version, to_version)

            if not path:
                result.success = True
                result.warnings.append("Nenhuma migração necessária")
                return result

            # Aplica migrações em sequência
            current_data = data
            for migration in path:
                logger.info(
                    f"Aplicando migração: {migration.source_version} -> "
                    f"{migration.target_version}"
                )

                try:
                    current_data = migration.migrate(current_data)
                    result.applied_migrations.append(
                        f"{migration.source_version} -> {migration.target_version}"
                    )
                except Exception as e:
                    result.errors.append(
                        f"Erro na migração {migration.source_version} -> "
                        f"{migration.target_version}: {e}"
                    )
                    return result

            result.data = current_data
            result.success = True
            result.stats["migrations_applied"] = len(path)

        except ValueError as e:
            result.errors.append(str(e))
        except Exception as e:
            result.errors.append(f"Erro inesperado: {e}")
            logger.exception("Erro durante migração")

        return result

    def auto_migrate(
        self,
        data: T,
        target_version: str | None = None,
    ) -> MigrationResult:
        """Detecta versão e migra automaticamente para a versão alvo.

        Args:
            data: Dados a serem migrados
            target_version: Versão alvo (usa latest se não especificado)

        Returns:
            Resultado da migração
        """
        # Detecta versão dos dados
        detected = self.detect_version(data)  # type: ignore[arg-type]

        if detected is None:
            return MigrationResult(
                success=False,
                data=data,
                source_version="unknown",
                target_version=target_version or self.target_version or "latest",
                errors=["Não foi possível detectar a versão dos dados"],
            )

        # Determina versão alvo
        tgt = target_version or self.target_version or self.get_latest_version()

        if tgt is None:
            return MigrationResult(
                success=False,
                data=data,
                source_version=detected,
                target_version="unknown",
                errors=["Nenhuma versão alvo definida"],
            )

        return self.migrate_data(data, detected, tgt)

    def migrate_spreadsheet(
        self,
        file_path: Path,
        target_version: str | None = None,
        output_path: Path | None = None,
        sheet_name: str | None = None,
    ) -> MigrationResult:
        """Migra uma planilha Excel para uma nova versão do schema.

        Args:
            file_path: Caminho da planilha
            target_version: Versão alvo (latest se não especificado)
            output_path: Caminho de saída (sobrescreve original se não especificado)
            sheet_name: Nome da aba (primeira aba se não especificado)

        Returns:
            Resultado da migração
        """
        if not HAS_PANDAS:
            return MigrationResult(
                success=False,
                data=None,
                source_version="unknown",
                target_version=target_version or "latest",
                errors=["pandas não está instalado"],
            )

        if not HAS_OPENPYXL:
            return MigrationResult(
                success=False,
                data=None,
                source_version="unknown",
                target_version=target_version or "latest",
                errors=["openpyxl não está instalado"],
            )

        try:
            # Lê planilha - se sheet_name for None, lê primeira aba
            if sheet_name is None:
                # Obtém nome da primeira aba
                xl = pd.ExcelFile(file_path)
                sheet_name = xl.sheet_names[0] if xl.sheet_names else "Sheet1"

            df = pd.read_excel(file_path, sheet_name=sheet_name)

            # Garante que df é um DataFrame (não dict de múltiplas abas)
            if isinstance(df, dict):
                df = list(df.values())[0]

            # Adiciona metadado de versão se existir

            # Converte para lista de dicionários
            records = df.to_dict("records")

            # Detecta versão do primeiro registro
            if not records:
                return MigrationResult(
                    success=False,
                    data=None,
                    source_version="unknown",
                    target_version=target_version or "latest",
                    errors=["Planilha está vazia"],
                )

            # Detecta versão baseada nos campos
            sample = records[0]
            detected = self.detect_version(sample)

            if detected is None:
                return MigrationResult(
                    success=False,
                    data=None,
                    source_version="unknown",
                    target_version=target_version or "latest",
                    errors=[
                        f"Não foi possível detectar versão. "
                        f"Campos encontrados: {list(sample.keys())}"
                    ],
                )

            # Determina versão alvo
            tgt = target_version or self.target_version or self.get_latest_version()

            if tgt is None:
                return MigrationResult(
                    success=False,
                    data=None,
                    source_version=detected,
                    target_version="unknown",
                    errors=["Nenhuma versão alvo definida"],
                )

            # Migra cada registro
            migrated_records = []
            errors = []
            warnings = []

            for i, record in enumerate(records):
                result = self.migrate_data(record, detected, tgt)

                if result.success:
                    migrated_records.append(result.data)
                    if result.warnings:
                        warnings.extend([f"Linha {i+2}: {w}" for w in result.warnings])
                else:
                    errors.extend([f"Linha {i+2}: {e}" for e in result.errors])
                    # Mantém registro original em caso de erro
                    migrated_records.append(record)

            # Cria DataFrame com dados migrados
            migrated_df = pd.DataFrame(migrated_records)

            # Determina caminho de saída
            out = output_path or file_path

            # Salva planilha
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                migrated_df.to_excel(writer, sheet_name=sheet_name or "Sheet1", index=False)

                # Adiciona metadados em aba separada
                metadata_df = pd.DataFrame(
                    {
                        "propriedade": ["schema_version", "migrated_from", "migrated_at"],
                        "valor": [tgt, detected, datetime.now().isoformat()],
                    }
                )
                metadata_df.to_excel(writer, sheet_name="_schema_metadata", index=False)

            return MigrationResult(
                success=len(errors) == 0 or len(migrated_records) > 0,
                data=out,
                source_version=detected,
                target_version=tgt,
                warnings=warnings,
                errors=errors,
                stats={
                    "rows_processed": len(records),
                    "rows_migrated": len(migrated_records),
                    "errors_count": len(errors),
                },
            )

        except Exception as e:
            logger.exception("Erro ao migrar planilha")
            return MigrationResult(
                success=False,
                data=None,
                source_version="unknown",
                target_version=target_version or "latest",
                errors=[f"Erro ao processar planilha: {e}"],
            )


# Schemas padrão para o sistema de upload do Mercado Livre

V1_0_FIELDS = {
    "sku": Field("sku", FieldType.STRING, required=True, description="SKU do produto"),
    "title": Field(
        "title",
        FieldType.STRING,
        required=True,
        description="Título do produto",
        aliases=["titulo", "nome"],
    ),
    "description": Field(
        "description", FieldType.STRING, description="Descrição", aliases=["descricao", "desc"]
    ),
    "price": Field(
        "price", FieldType.DECIMAL, required=True, description="Preço", aliases=["preco"]
    ),
    "currency": Field(
        "currency", FieldType.STRING, default="BRL", description="Moeda", aliases=["moeda"]
    ),
    "available_quantity": Field(
        "available_quantity",
        FieldType.INTEGER,
        default=1,
        description="Quantidade disponível",
        aliases=["quantidade", "qty", "estoque"],
    ),
    "category_id": Field(
        "category_id",
        FieldType.STRING,
        description="ID da categoria ML",
        aliases=["categoria", "category"],
    ),
    "condition": Field(
        "condition",
        FieldType.STRING,
        default="new",
        description="Condição (new/used)",
        aliases=["condicao"],
    ),
    "listing_type": Field(
        "listing_type",
        FieldType.STRING,
        default="gold_special",
        description="Tipo de listagem",
        aliases=["tipo_listagem"],
    ),
    "pictures": Field(
        "pictures",
        FieldType.LIST,
        description="URLs das imagens",
        aliases=["imagens", "images", "fotos"],
    ),
    "shipping_mode": Field(
        "shipping_mode",
        FieldType.STRING,
        default="me2",
        description="Modo de envio",
        aliases=["envio", "shipping"],
    ),
    "warranty": Field("warranty", FieldType.STRING, description="Garantia", aliases=["garantia"]),
}

V2_0_FIELDS = {
    **V1_0_FIELDS,
    "gtin": Field(
        "gtin",
        FieldType.STRING,
        description="Código GTIN/EAN",
        aliases=["ean", "barcode", "codigo_barras"],
    ),
    "brand": Field("brand", FieldType.STRING, description="Marca", aliases=["marca"]),
    "model": Field("model", FieldType.STRING, description="Modelo", aliases=["modelo"]),
    "attributes": Field(
        "attributes", FieldType.JSON, description="Atributos adicionais", aliases=["atributos"]
    ),
}

V3_0_FIELDS = {
    **V2_0_FIELDS,
    "video_id": Field(
        "video_id",
        FieldType.STRING,
        description="ID do vídeo no YouTube",
        aliases=["video", "youtube_id"],
    ),
    "sale_terms": Field(
        "sale_terms", FieldType.JSON, description="Termos de venda", aliases=["termos_venda"]
    ),
    "variations": Field(
        "variations", FieldType.JSON, description="Variações do produto", aliases=["variacoes"]
    ),
    "channels": Field(
        "channels",
        FieldType.LIST,
        description="Canais de venda",
        default=["marketplace"],
        aliases=["canais"],
    ),
}

# Schemas padrão
DEFAULT_SCHEMA_V1 = SchemaVersion(
    version="1.0",
    fields=V1_0_FIELDS,
    description="Schema inicial com campos básicos de produto",
)

DEFAULT_SCHEMA_V2 = SchemaVersion(
    version="2.0",
    fields=V2_0_FIELDS,
    description="Adiciona GTIN, marca, modelo e atributos",
)

DEFAULT_SCHEMA_V3 = SchemaVersion(
    version="3.0",
    fields=V3_0_FIELDS,
    description="Adiciona vídeo, termos de venda, variações e canais",
)


class V1ToV2Migration(Migration[dict[str, Any]]):
    """Migra schema v1.0 para v2.0."""

    source_version = "1.0"
    target_version = "2.0"
    description = "Adiciona campos GTIN, brand, model e attributes"

    def migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Migrate data from v1.0 to v2.0."""
        # Adiciona campos novos com valores padrão
        data["gtin"] = data.get("gtin", "")
        data["brand"] = data.get("brand", "")
        data["model"] = data.get("model", "")
        data["attributes"] = data.get("attributes", {})

        # Converte atributos de string para dict se necessário
        if isinstance(data["attributes"], str) and data["attributes"]:
            try:
                import json

                data["attributes"] = json.loads(data["attributes"])
            except json.JSONDecodeError:
                # Se não for JSON válido, trata como string simples
                data["attributes"] = {"raw": data["attributes"]}

        return data


class V2ToV3Migration(Migration[dict[str, Any]]):
    """Migra schema v2.0 para v3.0."""

    source_version = "2.0"
    target_version = "3.0"
    description = "Adiciona vídeo, sale_terms, variations e channels"

    def migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Migrate data from v2.0 to v3.0."""
        data["video_id"] = data.get("video_id", "")
        data["sale_terms"] = data.get("sale_terms", {})
        data["variations"] = data.get("variations", [])
        data["channels"] = data.get("channels", ["marketplace"])

        # Normaliza canais
        if isinstance(data["channels"], str):
            data["channels"] = [c.strip() for c in data["channels"].split(",")]

        return data


def create_default_migration_manager() -> MigrationManager:
    """Cria um MigrationManager com schemas e migrações padrão."""
    return MigrationManager(
        schemas=[DEFAULT_SCHEMA_V1, DEFAULT_SCHEMA_V2, DEFAULT_SCHEMA_V3],
        migrations=[V1ToV2Migration(), V2ToV3Migration()],
        target_version="3.0",
    )
