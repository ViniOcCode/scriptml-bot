"""Fiscal data domain model.

Based on Mercado Livre API documentation for fiscal information submission:
https://developers.mercadolivre.com.br/pt_br/envio-dos-dados-fiscais
"""

from dataclasses import dataclass, field
from typing import Any, Optional


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
    type: str = "single"

    # Measurement unit - "UN" (units), "KG", "LT", etc.
    measurement_unit: str = "UN"

    # Product cost (for tax calculation)
    cost: float = 0.0

    # Tax information
    ncm: str = ""  # NCM code (e.g., "39263000")
    origin_type: str = ""  # "reseller", "manufacturer", "importer"
    origin_detail: str = ""  # Origin detail code (e.g., "2" for national)

    # Optional tax fields
    cest: Optional[str] = None  # CEST code
    csosn: Optional[str] = None  # CSOSN for Simples Nacional (e.g., "500")
    tax_rule_id: Optional[int] = None  # Tax rule ID (for Regime Normal, leave empty for Simples)
    cfop: Optional[str] = None  # CFOP code
    fci: Optional[str] = None  # FCI (Ficha de Conteúdo de Importação)
    ex_tipi: Optional[str] = None  # EX TIPI code
    ean: Optional[str] = None  # EAN/GTIN barcode

    # ANVISA fields (for medical products)
    med_anvisa_code: Optional[str] = None  # ANVISA code or "ISENTO"
    med_exemption_reason: Optional[str] = None  # Reason for exemption

    # Weight information
    net_weight: Optional[float] = None  # Net weight in grams
    gross_weight: Optional[float] = None  # Gross weight in grams

    # Additional attributes storage
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Normalize fiscal data."""
        self.sku = str(self.sku).strip() if self.sku else ""
        self.title = str(self.title).strip() if self.title else ""
        self.type = str(self.type).strip() if self.type else "single"
        self.measurement_unit = str(self.measurement_unit).strip() if self.measurement_unit else "UN"
        self.ncm = str(self.ncm).strip() if self.ncm else ""
        self.origin_type = str(self.origin_type).strip() if self.origin_type else ""
        self.origin_detail = str(self.origin_detail).strip() if self.origin_detail else ""

        # Optional fields
        if self.cest:
            self.cest = str(self.cest).strip()
        if self.csosn:
            self.csosn = str(self.csosn).strip()
        if self.cfop:
            self.cfop = str(self.cfop).strip()
        if self.fci:
            self.fci = str(self.fci).strip()
        if self.ex_tipi:
            self.ex_tipi = str(self.ex_tipi).strip()
        if self.ean:
            self.ean = str(self.ean).strip()
        if self.med_anvisa_code:
            self.med_anvisa_code = str(self.med_anvisa_code).strip()
        if self.med_exemption_reason:
            self.med_exemption_reason = str(self.med_exemption_reason).strip()

        # Ensure cost is float
        if isinstance(self.cost, str):
            self.cost = float(self.cost.replace(",", "."))

        # Ensure weights are floats
        if self.net_weight is not None and isinstance(self.net_weight, str):
            self.net_weight = float(self.net_weight.replace(",", "."))
        if self.gross_weight is not None and isinstance(self.gross_weight, str):
            self.gross_weight = float(self.gross_weight.replace(",", "."))

    def to_api_payload(self) -> dict[str, Any]:
        """Convert to Mercado Livre API payload format.

        Returns:
            Dictionary formatted for /items/{item_id}/fiscal_info endpoint
        """
        payload: dict[str, Any] = {
            "sku": self.sku,
            "title": self.title,
            "type": self.type,
            "measurement_unit": self.measurement_unit,
            "cost": float(self.cost) if self.cost else 0.0,
            "tax_information": {}
        }

        tax_info: dict[str, Any] = payload["tax_information"]

        # Required tax fields
        if self.ncm:
            tax_info["ncm"] = self.ncm
        if self.origin_type:
            tax_info["origin_type"] = self.origin_type
        if self.origin_detail:
            tax_info["origin_detail"] = self.origin_detail

        # Optional tax fields
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

        # Weight fields
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
        - measurement_unit
        - cost
        - tax_information.ncm
        - tax_information.origin_type
        - tax_information.origin_detail
        """
        return bool(
            self.sku
            and self.title
            and self.type
            and self.measurement_unit
            and self.cost is not None
            and self.ncm
            and self.origin_type
            and self.origin_detail
        )

    @property
    def has_complete_tax_info(self) -> bool:
        """Check if all tax information fields are present."""
        return bool(
            self.ncm
            and self.origin_type
            and self.origin_detail
        )

    def get_missing_fields(self) -> list[str]:
        """Get list of missing required fields."""
        missing: list[str] = []
        if not self.sku:
            missing.append("sku")
        if not self.title:
            missing.append("title")
        if not self.type:
            missing.append("type")
        if not self.measurement_unit:
            missing.append("measurement_unit")
        if self.cost is None or self.cost == 0:
            missing.append("cost")
        if not self.ncm:
            missing.append("ncm")
        if not self.origin_type:
            missing.append("origin_type")
        if not self.origin_detail:
            missing.append("origin_detail")
        return missing

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
        **kwargs: Any
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
        origin_type: str = kwargs.pop("origin_type", "reseller")
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
            **kwargs
        )
