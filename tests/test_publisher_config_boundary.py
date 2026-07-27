"""Config boundary tests: publisher must not read builder config."""

from __future__ import annotations

from pathlib import Path

import pytest

from mercadolivre_upload.application.validators.seller_policy import load_seller_config
from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.shared.publisher_settings import load_publisher_settings


def test_publisher_code_does_not_reference_builder_config_files() -> None:
    root = Path(__file__).resolve().parents[1] / "mercadolivre_upload"
    forbidden_tokens = ("builder.yaml", "config/builder.yaml")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                violations.append(f"{path.relative_to(root)} contains {token!r}")
    assert not violations, "Publisher references builder config:\n" + "\n".join(sorted(violations))


def test_publisher_rejects_builder_owned_fields_in_config(tmp_path: Path) -> None:
    config_file = tmp_path / "publisher.yaml"
    config_file.write_text(
        "seller:\n"
        "  listing:\n"
        "    allowed_types: [gold_special]\n"
        "    default_type: gold_special\n"
        "  pricing:\n"
        "    min_price: 10\n"
        "    max_price: 100\n"
        "builder:\n"
        "  cache: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported top-level fields"):
        load_seller_config(config_file)


def test_publisher_uses_invocation_snapshot_instead_of_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_yaml = tmp_path / "publisher.yaml"
    monkeypatch.setenv(
        "MLBOT_PUBLISHER_CONFIG_SNAPSHOT",
        '{"seller":{"listing":{"allowed_types":["gold_pro"],"default_type":"gold_pro"},'
        '"pricing":{"min_price":10,"max_price":100},"batch":{"publish_inactive":true}}}',
    )

    config = load_seller_config(missing_yaml)

    assert config.listing.allowed_types == ["gold_pro"]
    assert config.batch.publish_inactive is True


def test_production_never_falls_back_to_publisher_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "publisher.yaml"
    config_file.write_text("seller: {}\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MLBOT_SETTINGS_DB", raising=False)
    monkeypatch.delenv("MLBOT_PUBLISHER_CONFIG_SNAPSHOT", raising=False)

    with pytest.raises(AuthError, match="database is required"):
        load_publisher_settings(config_file)


def test_publisher_configuration_rejects_embedded_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MLBOT_PUBLISHER_CONFIG_SNAPSHOT",
        '{"seller":{"client_secret":"must-not-be-here"}}',
    )

    with pytest.raises(AuthError, match="secret fields are forbidden"):
        load_publisher_settings()
