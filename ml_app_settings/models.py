from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnvRef(BaseModel):
    env: str


class FileRef(BaseModel):
    file: str


class SettingsSources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["canonical", "standalone"]
    settings_file: Path | None = None
    secret_sources: dict[str, str] = Field(default_factory=dict)
    cli_overrides: list[str] = Field(default_factory=list)


class SharedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_env: str = "development"
    workspace_dir: Path = Path("./workspace")
    cache_dir: Path = Path("./cache")
    reports_dir: Path = Path("./cache/reports")
    secrets_dir: Path = Path("./secrets")
    log_level: str = "INFO"
    dry_run: bool = False
    batch_size: int = 5
    max_skus: int = 10


class BuilderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller7_email: str = ""
    seller7_base_url: str = "https://app.seller7.com.br"
    google_drive_root_folder_ids: list[str] = Field(default_factory=list)
    use_batch_api: bool = False
    image_mock: bool = False
    cache: dict[str, Any] = Field(default_factory=dict)
    media_policy: dict[str, Any] = Field(default_factory=dict)
    listing_defaults: dict[str, Any] = Field(default_factory=dict)
    fiscal: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)
    ncm: dict[str, Any] = Field(default_factory=dict)

    @field_validator("google_drive_root_folder_ids", mode="before")
    @classmethod
    def _parse_root_folder_ids(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("google_drive_root_folder_ids must be a list or comma-separated string")


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    cache: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)


class ShippingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode_priority: list[str] = Field(default_factory=lambda: ["me2", "me1"])
    default_mode: str = "not_specified"
    policy: dict[str, Any] = Field(default_factory=dict)
    runtime_policy: dict[str, Any] = Field(default_factory=dict)


class SellerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing: dict[str, Any] = Field(default_factory=dict)
    pricing: dict[str, Any] = Field(default_factory=dict)
    categories: dict[str, Any] = Field(default_factory=dict)
    batch: dict[str, Any] = Field(default_factory=dict)


class FiscalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_fields: dict[str, Any] = Field(default_factory=dict)
    fiscal_defaults: dict[str, Any] = Field(default_factory=dict)
    field_mappings: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)


class MappingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_fields: dict[str, Any] = Field(default_factory=dict)
    attribute_rules: dict[str, Any] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)
    sanitizer: dict[str, Any] = Field(default_factory=dict)


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ml_client_id: str | EnvRef | FileRef | None = None
    ml_client_secret: str | EnvRef | FileRef | None = None
    redirect_uri: str = "http://localhost:8000/callback"
    token_path: Path = Path("./secrets/tokens.json")
    secure_storage: dict[str, Any] = Field(default_factory=dict)
    seller7_password: str | EnvRef | FileRef | None = None
    openrouter_api_key: str | EnvRef | FileRef | None = None
    google_drive_service_account_json: str | EnvRef | FileRef | None = None
    encryption_key: str | EnvRef | FileRef | None = None


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared: SharedSettings
    builder: BuilderConfig
    bot: BotConfig
    shipping: ShippingSettings
    seller: SellerSettings
    fiscal: FiscalSettings
    mapping: MappingSettings
    auth: AuthSettings
    sources: SettingsSources
