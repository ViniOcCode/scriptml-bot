from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml

from .models import AppSettings, EnvRef, FileRef, SettingsSources

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


_SECRET_ENV_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ml_client_id": ("ML_PIPE_MERCADO_LIVRE_CLIENT_ID",),
    "ml_client_secret": ("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET",),
    "seller7_password": ("ML_PIPE_SELLER7_PASSWORD",),
    "openrouter_api_key": ("ML_PIPE_OPENROUTER_API_KEY",),
    "google_drive_service_account_json": ("ML_PIPE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON",),
    "encryption_key": ("ML_PIPE_ENCRYPTION_KEY",),
}

_SECRET_FILE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ml_client_id": ("meli_client_id",),
    "ml_client_secret": ("ml_app_secret", "meli_client_secret"),
    "seller7_password": ("seller7_password",),
    "openrouter_api_key": ("openrouter_api_key",),
    "google_drive_service_account_json": ("google_drive_service_account_json",),
}

_SHARED_ENV_OVERRIDES: dict[str, str] = {
    "app_env": "ML_PIPE_ENV",
    "log_level": "ML_PIPE_LOG_LEVEL",
    "dry_run": "ML_PIPE_DRY_RUN",
    "max_skus": "ML_PIPE_MAX_SKUS",
    "secrets_dir": "ML_PIPE_SECRETS_DIR",
    "cache_dir": "ML_PIPE_CACHE_DIR",
}

_BUILDER_ENV_OVERRIDES: dict[str, str] = {
    "seller7_email": "ML_PIPE_SELLER7_EMAIL",
    "seller7_base_url": "ML_PIPE_SELLER7_BASE_URL",
    "google_drive_root_folder_ids": "ML_PIPE_GOOGLE_DRIVE_ROOT_FOLDER_IDS",
    "use_batch_api": "ML_PIPE_USE_BATCH_API",
    "image_mock": "ML_PIPE_IMAGE_MOCK",
}

_AUTH_ENV_OVERRIDES: dict[str, str] = {
    "redirect_uri": "ML_PIPE_MERCADO_LIVRE_REDIRECT_URI",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Failed to read settings file '{path}': {exc}") from exc
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in settings file '{path}'") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Settings file must contain a mapping: {path}")
    return payload


def _base_defaults() -> dict[str, Any]:
    return {
        "shared": {
            "app_env": "development",
            "workspace_dir": "./workspace",
            "cache_dir": "./cache",
            "reports_dir": "./cache/reports",
            "secrets_dir": "./secrets",
            "log_level": "INFO",
            "dry_run": False,
            "batch_size": 5,
            "max_skus": 10,
        },
        "builder": {
            "seller7_email": "",
            "seller7_base_url": "https://app.seller7.com.br",
            "google_drive_root_folder_ids": [],
            "use_batch_api": False,
            "image_mock": False,
            "cache": {
                "category_attributes_ttl_seconds": 86400,
                "sku_category_ttl_seconds": 86400,
                "enable_sku_category_cache": False,
            },
            "media_policy": {
                "dev_allow_ineligible_uploaded_images": False,
                "dev_emit_non_publishable_payload": True,
                "strict_publishable_media_only": None,
                "enable_filename_marketplace_hints": True,
                "generate_images_only_when_required_slots_missing": True,
            },
            "listing_defaults": {
                "listing_type": "gold_special",
                "shipping_mode": "me2",
                "local_pick_up": False,
                "free_shipping": False,
                "sale_terms_strict_evidence_only": False,
                "warranty_type": "Garantia do vendedor",
                "warranty_time": "30 dias",
            },
            "fiscal": {
                "csosn": "102",
                "is_manufacturer": False,
                "measurement_unit": "UN",
                "regime": "simples_nacional",
            },
            "models": {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "query_generation": "openrouter/free",
                "copy_generation": "openrouter/free",
                "structured_extraction": "openrouter/free",
                "vision_triage": "openrouter/free",
                "cover": "openrouter/free",
                "secondary_images": "openrouter/free",
                "fallback_validation": "openrouter/free",
                "seller7_timeout_seconds": 30.0,
                "ml_api_timeout_seconds": 30.0,
                "openrouter_http_timeout_seconds": 120.0,
                "openrouter_enable_rate_limit_retries": False,
                "openrouter_rate_limit_max_retries": 1,
                "openrouter_rate_limit_retry_window_seconds": 60,
            },
            "ncm": {
                "ncm_official_source_url": "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json",
                "ncm_sync_timeout_seconds": 30.0,
                "ncm_snapshot_dir": None,
                "ncm_enable_ai_reranking": False,
                "ncm_auto_apply_confidence_threshold": 0.8,
                "ncm_auto_apply_top1_margin_threshold": 0.15,
                "ncm_rerank_ambiguity_lower_confidence": 0.75,
                "ncm_rerank_ambiguity_upper_confidence": 0.90,
                "ncm_snapshot_max_age_hours": 168.0,
            },
        },
        "bot": {"publish": {"publish_inactive": False}, "runtime": {}, "cache": {}, "validation": {}},
        "shipping": {
            "mode_priority": ["me2", "me1"],
            "default_mode": "not_specified",
            "policy": {
                "non_blocking_codes": [
                    "shipping.free_shipping.cost_exceeded",
                    "item.shipping.mandatory_free_shipping",
                ],
                "mandatory_free_shipping_tags": ["mandatory_free_shipping"],
                "enforce_mandatory_free_shipping": True,
                "allow_runtime_tag_overrides": True,
                "allow_runtime_free_shipping_override": True,
            },
            "runtime_policy": {},
        },
        "seller": {
            "listing": {
                "allowed_types": [
                    "gold_special",
                    "gold_pro",
                    "gold_premium",
                    "gold",
                    "silver",
                    "bronze",
                    "free",
                ],
                "default_type": "gold_special",
            },
            "pricing": {"min_price": 0.01, "max_price": 999999.0},
            "categories": {"blocked": [], "overrides": {}},
            "batch": {
                "human_review_required": True,
                "publish_inactive": False,
                "min_ai_confidence": 0.0,
            },
        },
        "fiscal": {"fiscal_fields": {}, "fiscal_defaults": {}, "field_mappings": {}, "validation": {}},
        "mapping": {"standard_fields": {}, "attribute_rules": {}, "scoring": {}, "sanitizer": {}},
        "auth": {
            "ml_client_id": None,
            "ml_client_secret": None,
            "redirect_uri": "http://localhost:8000/callback",
            "token_path": "./secrets/tokens.json",
            "secure_storage": {"enabled": True},
            "seller7_password": None,
            "openrouter_api_key": None,
            "google_drive_service_account_json": None,
            "encryption_key": None,
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _extract_sanitizer(attribute_rules: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "protected_attributes",
        "na_policy",
        "similarity",
        "dimension_patterns",
    )
    return {key: copy.deepcopy(attribute_rules.get(key)) for key in keys if key in attribute_rules}


def _packaged_defaults() -> dict[str, Any]:
    payload = _base_defaults()

    builder_example = _first_existing(
        _REPO_ROOT / "apps/mlpayload-builder/settings.example.yaml",
        _REPO_ROOT / "settings.example.yaml",
    )
    if builder_example is not None:
        builder_raw = _read_yaml(builder_example)
        payload["builder"].update(
            {
                "cache": builder_raw.get("cache", {}),
                "media_policy": builder_raw.get("media_policy", {}),
                "listing_defaults": builder_raw.get("listing_defaults", {}),
                "fiscal": builder_raw.get("fiscal", {}),
                "models": builder_raw.get("models", {}),
            }
        )
        if "log_level" in builder_raw:
            payload["shared"]["log_level"] = builder_raw["log_level"]
        if "app_env" in builder_raw:
            payload["shared"]["app_env"] = builder_raw["app_env"]

    shipping_path = _first_existing(
        _REPO_ROOT / "apps/scriptml-bot/config/shipping.yaml",
        _REPO_ROOT / "config/shipping.yaml",
    )
    if shipping_path is not None:
        shipping_raw = _read_yaml(shipping_path)
        _deep_merge(payload["shipping"], shipping_raw.get("shipping", {}))

    attribute_rules_path = _first_existing(
        _REPO_ROOT / "apps/scriptml-bot/config/attribute_rules.yaml",
        _REPO_ROOT / "config/attribute_rules.yaml",
    )
    if attribute_rules_path is not None:
        attribute_rules_raw = _read_yaml(attribute_rules_path)
        payload["mapping"]["attribute_rules"] = attribute_rules_raw
        payload["mapping"]["scoring"] = copy.deepcopy(attribute_rules_raw.get("scoring", {}))
        payload["mapping"]["sanitizer"] = _extract_sanitizer(attribute_rules_raw)

    standard_fields_path = _first_existing(
        _REPO_ROOT / "apps/scriptml-bot/config/standard_fields.yaml",
        _REPO_ROOT / "config/standard_fields.yaml",
    )
    if standard_fields_path is not None:
        payload["mapping"]["standard_fields"] = _read_yaml(standard_fields_path)

    fiscal_path = _first_existing(
        _REPO_ROOT / "apps/scriptml-bot/config/fiscal_config.yaml",
        _REPO_ROOT / "config/fiscal_config.yaml",
    )
    if fiscal_path is not None:
        fiscal_raw = _read_yaml(fiscal_path)
        payload["fiscal"] = {
            "fiscal_fields": copy.deepcopy(fiscal_raw.get("fiscal_fields", {})),
            "fiscal_defaults": copy.deepcopy(fiscal_raw.get("fiscal_defaults", {})),
            "field_mappings": copy.deepcopy(fiscal_raw.get("fiscal_fields", {})),
            "validation": {},
        }

    seller_path = _first_existing(
        _REPO_ROOT / "apps/scriptml-bot/config/seller.example.dev.yaml",
        _REPO_ROOT / "config/seller.example.dev.yaml",
    )
    if seller_path is not None:
        seller_raw = _read_yaml(seller_path)
        payload["seller"] = copy.deepcopy(seller_raw.get("seller", seller_raw))

    return payload


def _is_canonical_payload(raw: dict[str, Any]) -> bool:
    required = {"shared", "builder", "bot", "shipping", "seller", "fiscal", "mapping", "auth"}
    return required.issubset(raw.keys())


def _coerce_legacy_payload(raw: dict[str, Any], app: Literal["builder", "bot"] | None) -> dict[str, Any]:
    if _is_canonical_payload(raw):
        return raw

    payload = _packaged_defaults()

    if app == "builder" and any(key in raw for key in ("cache", "media_policy", "listing_defaults", "models", "fiscal", "ncm")):
        payload["builder"]["cache"] = copy.deepcopy(raw.get("cache", {}))
        payload["builder"]["media_policy"] = copy.deepcopy(raw.get("media_policy", {}))
        payload["builder"]["listing_defaults"] = copy.deepcopy(raw.get("listing_defaults", {}))
        payload["builder"]["fiscal"] = copy.deepcopy(raw.get("fiscal", {}))
        payload["builder"]["models"] = copy.deepcopy(raw.get("models", {}))
        if "ncm" in raw:
            payload["builder"]["ncm"] = copy.deepcopy(raw.get("ncm", {}))
        if "workspace" in raw and isinstance(raw["workspace"], dict):
            cache_dir = raw["workspace"].get("cache_dir")
            if cache_dir is not None:
                payload["shared"]["cache_dir"] = cache_dir
        for key in ("app_env", "log_level", "dry_run"):
            if key in raw:
                payload["shared"][key] = raw[key]
        return payload

    if set(raw).issubset({"app_env", "log_level", "paths", "defaults", "services"}):
        paths = raw.get("paths", {}) if isinstance(raw.get("paths"), dict) else {}
        defaults = raw.get("defaults", {}) if isinstance(raw.get("defaults"), dict) else {}
        services = raw.get("services", {}) if isinstance(raw.get("services"), dict) else {}
        payload["shared"].update(
            {
                "app_env": raw.get("app_env", payload["shared"]["app_env"]),
                "log_level": raw.get("log_level", payload["shared"]["log_level"]),
                "workspace_dir": paths.get("workspace", payload["shared"]["workspace_dir"]),
                "cache_dir": paths.get("cache", payload["shared"]["cache_dir"]),
                "reports_dir": paths.get("reports", payload["shared"]["reports_dir"]),
                "secrets_dir": paths.get("secrets_dir", payload["shared"]["secrets_dir"]),
                "batch_size": defaults.get("batch_size", payload["shared"]["batch_size"]),
                "max_skus": defaults.get("max_skus", payload["shared"]["max_skus"]),
            }
        )
        payload["bot"]["publish"]["publish_inactive"] = defaults.get("publish_inactive", False)
        mercado_livre = services.get("mercado_livre", {}) if isinstance(services.get("mercado_livre"), dict) else {}
        seller7 = services.get("seller7", {}) if isinstance(services.get("seller7"), dict) else {}
        openrouter = services.get("openrouter", {}) if isinstance(services.get("openrouter"), dict) else {}
        payload["auth"]["redirect_uri"] = mercado_livre.get("redirect_uri", payload["auth"]["redirect_uri"])
        if "token_path" in mercado_livre:
            payload["auth"]["token_path"] = mercado_livre["token_path"]
        payload["builder"]["seller7_base_url"] = seller7.get("base_url", payload["builder"]["seller7_base_url"])
        if "base_url" in openrouter:
            payload["builder"]["models"]["openrouter_base_url"] = openrouter["base_url"]
        return payload

    raise ValueError("Unsupported settings file schema for shared loader")


def _normalize_relative_paths(raw: dict[str, Any], base_dir: Path) -> None:
    shared = raw.get("shared", {})
    if isinstance(shared, dict):
        for key in ("workspace_dir", "cache_dir", "reports_dir", "secrets_dir"):
            value = shared.get(key)
            if value is None:
                continue
            path = Path(str(value)).expanduser()
            shared[key] = path if path.is_absolute() else base_dir / path
    auth = raw.get("auth", {})
    if isinstance(auth, dict):
        token_path = auth.get("token_path")
        if token_path is not None:
            path = Path(str(token_path)).expanduser()
            auth["token_path"] = path if path.is_absolute() else base_dir / path
    builder = raw.get("builder", {})
    if isinstance(builder, dict):
        ncm = builder.get("ncm")
        if isinstance(ncm, dict) and ncm.get("ncm_snapshot_dir"):
            path = Path(str(ncm["ncm_snapshot_dir"])).expanduser()
            ncm["ncm_snapshot_dir"] = path if path.is_absolute() else base_dir / path


def _resolve_secret_ref(
    *,
    name: str,
    value: Any,
    secrets_dir: Path,
    secret_sources: dict[str, str],
) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"env"}:
        env_name = str(value["env"])
        raw = os.getenv(env_name)
        if raw is None or raw.strip() == "":
            raise ValueError(f"Unresolved required secret ref for {name}: {env_name}")
        secret_sources[name] = f"env:{env_name}"
        return raw.strip()
    if isinstance(value, dict) and set(value.keys()) == {"file"}:
        ref_path = Path(str(value["file"])).expanduser()
        candidate = ref_path if ref_path.is_absolute() else secrets_dir / ref_path
        raw = candidate.read_text(encoding="utf-8").strip()
        if not raw:
            raise ValueError(f"Secret file '{candidate}' is empty after trimming whitespace.")
        secret_sources[name] = f"file:{candidate}"
        return raw
    if isinstance(value, str) and value.strip():
        return value.strip()

    for candidate_name in _SECRET_FILE_CANDIDATES.get(name, ()):
        candidate = secrets_dir / candidate_name
        if candidate.exists():
            raw = candidate.read_text(encoding="utf-8").strip()
            if not raw:
                raise ValueError(f"Secret file '{candidate}' is empty after trimming whitespace.")
            secret_sources[name] = "secrets dir"
            return raw

    for env_name in _SECRET_ENV_CANDIDATES.get(name, ()):
        raw = os.getenv(env_name)
        if raw is None or raw.strip() == "":
            continue
        secret_sources[name] = f"env:{env_name}"
        return raw.strip()

    return None


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    shared = raw["shared"]
    builder = raw["builder"]
    auth = raw["auth"]

    for key, env_name in _SHARED_ENV_OVERRIDES.items():
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value.strip() == "":
            continue
        if key == "dry_run":
            shared[key] = _parse_bool(raw_value)
        elif key == "max_skus":
            shared[key] = int(raw_value.strip())
        else:
            shared[key] = raw_value.strip()

    for key, env_name in _BUILDER_ENV_OVERRIDES.items():
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value.strip() == "":
            continue
        if key in {"use_batch_api", "image_mock"}:
            builder[key] = _parse_bool(raw_value)
        elif key == "google_drive_root_folder_ids":
            builder[key] = [item.strip() for item in raw_value.split(",") if item.strip()]
        else:
            builder[key] = raw_value.strip()

    for key, env_name in _AUTH_ENV_OVERRIDES.items():
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value.strip() == "":
            continue
        auth[key] = raw_value.strip()


def _apply_cli_overrides(raw: dict[str, Any], cli_overrides: dict[str, Any] | None) -> list[str]:
    if not cli_overrides:
        return []
    applied: list[str] = []
    for key, value in cli_overrides.items():
        if value is None:
            continue
        applied.append(key)
        parts = key.split(".")
        target: Any = raw
        for part in parts[:-1]:
            if not isinstance(target, dict):
                break
            target = target.setdefault(part, {})
        if isinstance(target, dict):
            target[parts[-1]] = value
    return applied


def _resolve_explicit_settings_path(raw_path: str) -> Path:
    explicit_path = Path(raw_path).expanduser()
    if not explicit_path.exists() and not explicit_path.is_absolute():
        repo_relative = (_REPO_ROOT / explicit_path).resolve()
        if repo_relative.exists():
            explicit_path = repo_relative
    return explicit_path



def _load_effective_payload(app: Literal["builder", "bot"] | None) -> tuple[dict[str, Any], SettingsSources, Path]:
    # Use app-specific explicit env var if provided; do not auto-load APP_SETTINGS_FILE or ML_PIPE_SETTINGS_FILE
    if app == "builder":
        app_env_var = "ML_BUILDER_SETTINGS_FILE"
        autodiscovery_candidates = (
            _REPO_ROOT / "config/builder.yaml",
            _REPO_ROOT.parent / "config/builder.yaml",
        )
    elif app == "bot":
        app_env_var = "ML_PUBLISHER_SETTINGS_FILE"
        autodiscovery_candidates = (
            _REPO_ROOT / "config/publisher.yaml",
            _REPO_ROOT.parent / "config/publisher.yaml",
        )
    else:
        app_env_var = None
        autodiscovery_candidates = (
            _REPO_ROOT / "config/settings.yaml",
            _REPO_ROOT.parent / "config/settings.yaml",
        )

    explicit_app_settings = os.getenv(app_env_var) if app_env_var else None

    if explicit_app_settings and explicit_app_settings.strip():
        resolved_explicit_path = _resolve_explicit_settings_path(explicit_app_settings.strip())
        if not resolved_explicit_path.exists():
            raise FileNotFoundError(f"Configured settings file does not exist: {explicit_app_settings.strip()}")
        payload = _coerce_legacy_payload(_read_yaml(resolved_explicit_path), app)
        sources = SettingsSources(mode="canonical", settings_file=resolved_explicit_path)
        return payload, sources, resolved_explicit_path.parent

    autodiscovered_settings = _first_existing(*autodiscovery_candidates)
    if autodiscovered_settings is not None:
        payload = _coerce_legacy_payload(_read_yaml(autodiscovered_settings), app)
        sources = SettingsSources(mode="canonical", settings_file=autodiscovered_settings)
        base_dir = autodiscovered_settings.parent
        # When config is at <project_root>/config/publisher.yaml, resolve paths relative to project root
        if (
            autodiscovered_settings.name == "publisher.yaml"
            and autodiscovered_settings.parent.name == "config"
            and autodiscovered_settings.parent.parent == _REPO_ROOT
        ):
            base_dir = _REPO_ROOT
        return payload, sources, base_dir

    payload = _packaged_defaults()
    if app == "builder":
        base_dir = _first_existing(_REPO_ROOT / "apps/mlpayload-builder", _REPO_ROOT) or _REPO_ROOT
    elif app == "bot":
        base_dir = _first_existing(_REPO_ROOT / "apps/scriptml-bot", _REPO_ROOT) or _REPO_ROOT
    else:
        base_dir = _REPO_ROOT
    sources = SettingsSources(mode="standalone", settings_file=None)
    return payload, sources, base_dir


def load_app_settings(
    app: Literal["builder", "bot"] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AppSettings:
    raw, sources, base_dir = _load_effective_payload(app)
    _normalize_relative_paths(raw, base_dir)
    _apply_env_overrides(raw)
    sources.cli_overrides = _apply_cli_overrides(raw, cli_overrides)

    secrets_dir = Path(raw["shared"]["secrets_dir"])
    auth = raw["auth"]
    for field_name in (
        "ml_client_id",
        "ml_client_secret",
        "seller7_password",
        "openrouter_api_key",
        "google_drive_service_account_json",
        "encryption_key",
    ):
        resolved = _resolve_secret_ref(
            name=field_name,
            value=auth.get(field_name),
            secrets_dir=secrets_dir,
            secret_sources=sources.secret_sources,
        )
        auth[field_name] = resolved

    raw["sources"] = sources.model_dump()
    settings = AppSettings.model_validate(raw)

    # Prevent inline secret leakage in canonical config when explicit refs were present.
    if isinstance(settings.auth.google_drive_service_account_json, str):
        raw_secret = settings.auth.google_drive_service_account_json.strip()
        if raw_secret and raw_secret.endswith(".json"):
            raise ValueError(
                "google_drive_service_account_json must contain the full JSON content, not a file path"
            )
        if raw_secret:
            try:
                parsed = json.loads(raw_secret)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "google_drive_service_account_json must contain the full JSON content, not a file path"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError("google_drive_service_account_json must be a JSON object.")

    return settings
