"""Spreadsheet parser adapter.

Provides a flexible parser that normalizes Excel/CSV data to Portuguese field names.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from mercadolivre_upload.domain.text_normalizer import PortugueseTextNormalizer

logger = logging.getLogger(__name__)


class SpreadsheetParser:
    """Parse spreadsheet files into normalized dictionaries."""

    SUPPORTED_EXTENSIONS = {".xlsx", ".xls"}

    DEFAULT_COLUMN_MAPPING = {
        "title": "titulo",
        "titulo": "titulo",
        "título": "titulo",
        "price": "preco",
        "preco": "preco",
        "preço": "preco",
        "category": "categoria",
        "categoria": "categoria",
        "category_id": "categoria",
        "currency": "moeda",
        "moeda": "moeda",
        "currency_id": "moeda",
        "quantity": "quantidade",
        "quantidade": "quantidade",
        "available_quantity": "quantidade",
        "condition": "condicao",
        "condicao": "condicao",
        "condição": "condicao",
        "description": "descricao",
        "descricao": "descricao",
        "descrição": "descricao",
        "sku": "sku",
        "codigo": "sku",
        "código": "sku",
        "code": "sku",
        "ean": "gtin",
        "gtin": "gtin",
        "brand": "marca",
        "marca": "marca",
        "images": "imagens",
        "imagens": "imagens",
    }

    def __init__(self, column_mapping: dict | None = None):
        self._column_mapping = (
            dict(column_mapping) if column_mapping else self.DEFAULT_COLUMN_MAPPING.copy()
        )
        self._data: list[dict] = []

    def parse(
        self,
        file_path: str | Path,
        sheet_name: str | int | None = None,
        header_row: int | None = None,
    ) -> list[dict]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError("Arquivo não encontrado")
        if file_path.is_dir():
            raise ValueError("Caminho não é um arquivo")
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Formato de arquivo não suportado: {file_path.suffix.lower()}")

        logger.info(f"Lendo planilha: {file_path}")

        try:
            if file_path.suffix.lower() == ".xls":
                df = pd.read_excel(file_path, sheet_name=sheet_name, engine="xlrd")
            else:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception as exc:
            raise ValueError("Erro ao ler arquivo Excel") from exc

        if isinstance(df, dict):
            if df:
                df = next(iter(df.values()))
            else:
                df = pd.DataFrame()

        if df.empty:
            logger.warning("Planilha vazia")
            return []

        if header_row is not None:
            if file_path.suffix.lower() == ".xls":
                df = pd.read_excel(
                    file_path, sheet_name=sheet_name, header=header_row, engine="xlrd"
                )
            else:
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
            if isinstance(df, dict):
                if df:
                    df = next(iter(df.values()))
                else:
                    df = pd.DataFrame()

        if header_row is not None:
            df.columns = [str(col).strip() for col in df.columns]
        df = self._normalize_columns(df)

        records = df.to_dict(orient="records")
        cleaned = [self._clean_record(record) for record in records]
        self._data = [record for record in cleaned if record]
        logger.info(f"Parsed {len(self._data)} registros")
        return list(self._data)

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        mapping = {}
        for column in df.columns:
            column_str = str(column).strip()
            normalized = PortugueseTextNormalizer.normalize(column_str)
            target = self._column_mapping.get(normalized) or self._column_mapping.get(
                column_str.lower()
            )
            mapping[column] = target or column_str.lower()
        return df.rename(columns=mapping)

    def _clean_record(self, record: dict) -> dict:
        cleaned: dict = {}
        for key, value in record.items():
            if value is None:
                continue
            if isinstance(value, float) and pd.isna(value):
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    continue
                cleaned[key] = stripped
            else:
                cleaned[key] = value
        return cleaned

    def get_column_mapping(self) -> dict:
        return dict(self._column_mapping)

    def set_column_mapping(self, mapping: dict) -> None:
        self._column_mapping = dict(mapping)

    def get_supported_columns(self) -> list[str]:
        return list(set(self._column_mapping.values()))

    def validate_file(self, file_path: str | Path) -> tuple[bool, list[str]]:
        path = Path(file_path)
        errors: list[str] = []
        if not path.exists():
            return False, ["Arquivo não encontrado"]
        if path.is_dir():
            return False, ["Caminho não é um arquivo"]
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            return False, ["Formato de arquivo não suportado"]
        try:
            self.parse(path)
            return True, []
        except Exception as exc:
            errors.append(str(exc))
            return False, errors
