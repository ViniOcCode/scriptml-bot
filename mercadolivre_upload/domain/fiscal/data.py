"""Fiscal data domain model.

Based on Mercado Livre API documentation for fiscal information submission:
https://developers.mercadolivre.com.br/pt_br/envio-dos-dados-fiscais

Uses configuration from config/fiscal_config.yaml as the single source of truth for defaults.
"""

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mercadolivre_upload.shared.utils.config_loader import load_yaml_config

logger = logging.getLogger(__name__)


def _is_blank_value(value: Any) -> bool:
    """Return True when value is empty-like for fiscal payloads."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null"}
    return isinstance(value, float) and math.isnan(value)


def _normalize_optional_text(value: Any) -> str | None:
    """Normalize optional text fields, dropping empty-like values."""
    if _is_blank_value(value):
        return None
    return str(value).strip()


def _parse_float(value: Any) -> float | None:
    """Parse numeric values from strings/numbers, returning None when empty."""
    if _is_blank_value(value):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return None if math.isnan(numeric) else numeric
    try:
        numeric = float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return None if math.isnan(numeric) else numeric


def _load_fiscal_config() -> dict[str, Any]:
    """Load full fiscal config from config file.

    Returns:
        Full fiscal configuration dictionary
    """
    try:
        return load_yaml_config(Path("config/fiscal_config.yaml"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not load fiscal config: %s. Using empty config.", exc)
        return {}


def _load_fiscal_defaults() -> dict[str, Any]:
    """Load fiscal defaults from config file."""
    return _load_fiscal_config().get("fiscal_defaults", {})  # type: ignore[no-any-return]


def _load_field_value_mappings(field_name: str) -> dict[str, str]:
    """Load value_mappings for a specific fiscal field from config.

    Args:
        field_name: The field name in fiscal_fields config (e.g., 'origin_type', 'origin_detail')

    Returns:
        Dictionary mapping input values to API values
    """
    config = _load_fiscal_config()
    fields = config.get("fiscal_fields", {})
    field_config = fields.get(field_name, {})
    return field_config.get("value_mappings", {})  # type: ignore[no-any-return]


@dataclass
class FiscalData:
    """Fiscal data for products.

    Stores all required and optional fields for Mercado Livre fiscal information.
    This data is submitted after item publication via the /items/{item_id}/fiscal_info endpoint.

    Required fields per ML API:
    - sku: Product SKU
    - title: Product title
    - type: Product type ("single" for individual items)
    - measurement_unit: Unit of measurement (e.g., "UN" for units)
    - cost: Product cost for tax calculation
    - tax_information: Nested tax information object
    """

    # Product identification
    sku: str
    title: str

    # Product type - "single" for individual items, "variation" for products with variations
    type: str = ""

    # Measurement unit - "UN" (units), "KG", "LT", etc.
    measurement_unit: str = ""

    # Product cost (for tax calculation)
    cost: float = 0.0

    # Tax payer type - required by ML API ("individual" or "company")
    tax_payer_type: str = "company"  # Default to "company"

    # Tax information
    ncm: str = ""  # NCM code (e.g., "39263000")
    origin_type: str = ""  # "reseller", "manufacturer", "importer"
    origin_detail: str = ""  # Origin detail code (e.g., "0" for national, range 0-8)

    # Optional tax fields
    cest: str | None = None  # CEST code
    csosn: str | None = None  # CSOSN for Simples Nacional (e.g., "500")
    tax_rule_id: int | None = None  # Tax rule ID (for Regime Normal, leave empty for Simples)
    cfop: str | None = None  # CFOP code
    fci: str | None = None  # FCI (Ficha de Conteúdo de Importação)
    ex_tipi: str | None = None  # EX TIPI code
    ean: str | None = None  # EAN/GTIN barcode

    # ANVISA fields (for medical products)
    med_anvisa_code: str | None = None  # ANVISA code or "ISENTO"
    med_exemption_reason: str | None = None  # Reason for exemption

    # Weight information (ML fiscal API expects kilograms)
    net_weight: float | None = None  # Net weight in kg
    gross_weight: float | None = None  # Gross weight in kg

    # Additional attributes storage
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize fiscal data using config defaults and value mappings."""
        # Load defaults from config (single source of truth)
        defaults = _load_fiscal_defaults()

        self.sku = str(self.sku).strip() if self.sku else ""
        self.title = str(self.title).strip() if self.title else ""
        # Use config defaults for type and measurement_unit
        self.type = str(self.type).strip() if self.type else defaults.get("type", "")
        self.measurement_unit = (
            str(self.measurement_unit).strip()
            if self.measurement_unit
            else defaults.get("measurement_unit", "")
        )

        # Sanitize NCM: remove dots/dashes, keep only digits
        ncm_raw = str(self.ncm).strip() if self.ncm else ""
        self.ncm = re.sub(r"[.\-/\s]", "", ncm_raw)

        # Sanitize origin_type using config-driven value mappings
        # ML API expects: "manufacturer", "reseller", or "imported"
        origin_type_str = str(self.origin_type).strip() if self.origin_type else ""
        origin_type_mappings = _load_field_value_mappings("origin_type")
        mapped_origin_type = origin_type_mappings.get(origin_type_str.lower(), "")
        if mapped_origin_type:
            self.origin_type = mapped_origin_type
        elif not origin_type_str:
            self.origin_type = defaults.get("origin_type", "")
        else:
            logger.warning(
                f"Unmapped origin_type value: '{origin_type_str}'. "
                f"Using config default: '{defaults.get('origin_type', '')}'"
            )
            self.origin_type = defaults.get("origin_type", "")

        # Sanitize origin_detail: extract digit 0-8 from strings like "0 - NACIONAL..."
        origin_detail_str = str(self.origin_detail).strip() if self.origin_detail else ""
        if origin_detail_str:
            # Try config-driven value mappings first
            origin_detail_mappings = _load_field_value_mappings("origin_detail")
            mapped = origin_detail_mappings.get(origin_detail_str.lower(), "")
            if mapped:
                self.origin_detail = mapped
            else:
                # Extract leading digit from format like "0 - NACIONAL..."
                match = re.match(r"^(\d)", origin_detail_str)
                if match:
                    self.origin_detail = match.group(1)
                else:
                    logger.warning(
                        f"Could not extract origin_detail digit from: '{origin_detail_str}'"
                    )
                    self.origin_detail = ""

        # Sanitize CSOSN: extract numeric prefix from "102 - TRIBUTADA..."
        csosn_str = _normalize_optional_text(self.csosn)
        if csosn_str:
            csosn_match = re.match(r"^(\d+)", csosn_str)
            if csosn_match:
                self.csosn = csosn_match.group(1)
            else:
                self.csosn = None
        else:
            self.csosn = None

        # Use config default for tax_payer_type if not set
        if not self.tax_payer_type:
            self.tax_payer_type = defaults.get("tax_payer_type", "")

        # Optional fields
        self.cest = _normalize_optional_text(self.cest)
        self.cfop = _normalize_optional_text(self.cfop)
        self.fci = _normalize_optional_text(self.fci)
        self.ex_tipi = _normalize_optional_text(self.ex_tipi)
        self.ean = _normalize_optional_text(self.ean)
        self.med_anvisa_code = _normalize_optional_text(self.med_anvisa_code)
        self.med_exemption_reason = _normalize_optional_text(self.med_exemption_reason)

        if _is_blank_value(self.tax_rule_id):
            self.tax_rule_id = None
        elif isinstance(self.tax_rule_id, str):
            try:
                self.tax_rule_id = int(self.tax_rule_id.strip())
            except ValueError:
                self.tax_rule_id = None

        # Ensure cost/weights are numeric and MLB-safe
        parsed_cost = _parse_float(self.cost)
        self.cost = parsed_cost if parsed_cost is not None else 0.0
        self.net_weight = _parse_float(self.net_weight)
        self.gross_weight = _parse_float(self.gross_weight)

    def to_api_payload(self) -> dict[str, Any]:
        """Convert to Mercado Livre API payload format.

        Returns:
            Dictionary formatted for /items/fiscal_information endpoint
        """
        payload: dict[str, Any] = {
            "sku": self.sku,
            "title": self.title,
            "type": self.type,
            "cost": float(self.cost) if self.cost is not None else 0.0,
            "tax_payer_type": self.tax_payer_type,
            "tax_information": {},
        }
        if self.measurement_unit:
            payload["measurement_unit"] = self.measurement_unit

        tax_info: dict[str, Any] = payload["tax_information"]

        # Required tax fields (always include if present)
        if self.ncm:
            tax_info["ncm"] = self.ncm
        if self.origin_type:
            tax_info["origin_type"] = self.origin_type
        if self.origin_detail:
            tax_info["origin_detail"] = self.origin_detail

        # Optional tax fields (only include if they have values)
        if self.cest:
            tax_info["cest"] = self.cest
        if self.csosn:
            tax_info["csosn"] = self.csosn
        if self.tax_rule_id is not None:
            tax_info["tax_rule_id"] = self.tax_rule_id
        if self.cfop:
            tax_info["cfop"] = self.cfop
        if self.fci:
            tax_info["fci"] = self.fci
        if self.ex_tipi:
            tax_info["ex_tipi"] = self.ex_tipi
        if self.ean:
            tax_info["ean"] = self.ean

        # ANVISA fields
        if self.med_anvisa_code:
            tax_info["med_anvisa_code"] = self.med_anvisa_code
        if self.med_exemption_reason:
            tax_info["med_exemption_reason"] = self.med_exemption_reason

        # Weight fields are sent in kg as expected by MLB fiscal API
        if self.net_weight is not None:
            tax_info["net_weight"] = float(self.net_weight)
        if self.gross_weight is not None:
            tax_info["gross_weight"] = float(self.gross_weight)

        return payload

    @property
    def is_valid(self) -> bool:
        """Check if required fields are present for fiscal submission.

        Required fields per ML API documentation:
        - sku
        - title
        - type
        - cost
        - tax_information.ncm
        - tax_information.origin_type
        - tax_information.origin_detail
        """
        return bool(
            self.sku
            and self.title
            and self.type
            and self.cost is not None
            and self.cost > 0
            and self.ncm
            and self.origin_type
            and self.origin_detail
        )

    @property
    def has_complete_tax_info(self) -> bool:
        """Check if all tax information fields are present."""
        return bool(self.ncm and self.origin_type and self.origin_detail)

    def get_missing_fields(self) -> list[str]:
        """Get list of missing required fields."""
        missing: list[str] = []
        if not self.sku:
            missing.append("sku")
        if not self.title:
            missing.append("title")
        if not self.type:
            missing.append("type")
        if self.cost is None or self.cost <= 0 or math.isnan(self.cost):
            missing.append("cost")
        if not self.ncm:
            missing.append("ncm")
        if not self.origin_type:
            missing.append("origin_type")
        if not self.origin_detail:
            missing.append("origin_detail")
        return missing

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all fiscal data fields
        """
        return {
            "sku": self.sku,
            "title": self.title,
            "type": self.type,
            "measurement_unit": self.measurement_unit,
            "cost": self.cost,
            "ncm": self.ncm,
            "origin_type": self.origin_type,
            "origin_detail": self.origin_detail,
            "cest": self.cest,
            "csosn": self.csosn,
            "tax_rule_id": self.tax_rule_id,
            "cfop": self.cfop,
            "fci": self.fci,
            "ex_tipi": self.ex_tipi,
            "ean": self.ean,
            "med_anvisa_code": self.med_anvisa_code,
            "med_exemption_reason": self.med_exemption_reason,
            "net_weight": self.net_weight,
            "gross_weight": self.gross_weight,
            "attributes": self.attributes,
        }

    @classmethod
    def from_spreadsheet_row(
        cls,
        sku: str,
        title: str,
        cost: float,
        ncm: str,
        origin: str,
        cfop: str = "",
        cest: str = "",
        **kwargs: Any,
    ) -> "FiscalData":
        """Create FiscalData from spreadsheet row values.

        This factory method handles the common case where data comes from
        the spreadsheet parser with standard column names.

        Args:
            sku: Product SKU
            title: Product title
            cost: Product cost
            ncm: NCM code
            origin: Origin code (maps to origin_detail)
            cfop: CFOP code (optional)
            cest: CEST code (optional)
            **kwargs: Additional fields

        Returns:
            FiscalData instance
        """
        # Map common spreadsheet column names to API fields
        defaults = _load_fiscal_defaults()
        origin_type: str = kwargs.pop("origin_type", defaults.get("origin_type", ""))
        origin_detail: str = origin  # Spreadsheet "origin" maps to origin_detail

        return cls(
            sku=sku,
            title=title,
            cost=cost,
            ncm=ncm,
            origin_type=origin_type,
            origin_detail=origin_detail,
            cfop=cfop or None,
            cest=cest or None,
            **kwargs,
        )
