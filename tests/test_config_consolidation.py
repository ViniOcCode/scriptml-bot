"""Regression tests for split config consolidation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

from mercadolivre_upload.cli.commands import upload as upload_command
from mercadolivre_upload.domain.shipping import resolver as shipping_resolver
from mercadolivre_upload.domain.validation import sanitizer as sanitizer_module
from mercadolivre_upload.shared.utils.config_loader import load_merged_yaml_config


def _write(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class _ShippingProvider:
    def __init__(self, user_info: dict[str, Any], shipping_preferences: dict[str, Any]):
        self.user_info = user_info
        self.shipping_preferences = shipping_preferences

    def get_users_me(self) -> dict[str, Any]:
        return self.user_info

    def get_user_shipping_preferences(self, user_id: str) -> dict[str, Any]:  # noqa: ARG002
        return self.shipping_preferences


def test_load_merged_yaml_config_precedence(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    fallback = config_dir / "fiscal_config.yaml"
    primary_a = config_dir / "standard_fields.yaml"
    primary_b = config_dir / "shipping.yaml"

    _write(
        fallback,
        """
        source: fallback
        shared: fallback
        fallback_only: true
        nested:
          owner: fallback
        """,
    )
    _write(
        primary_a,
        """
        source: split-a
        shared: split-a
        split_a_only: true
        nested:
          owner: split-a
        """,
    )
    _write(
        primary_b,
        """
        source: split-b
        shared: split-b
        split_b_only: true
        """,
    )

    config = load_merged_yaml_config(primary_a, primary_b, fallback=fallback)

    assert config["fallback_only"] is True
    assert config["split_a_only"] is True
    assert config["split_b_only"] is True
    assert config["source"] == "split-b"
    assert config["shared"] == "split-b"
    assert config["nested"] == {"owner": "split-a"}


def test_upload_load_config_merges_split_files_only(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write(
        config_dir / "fiscal_config.yaml",
        """
        fiscal_only: true
        shared: fiscal
        """,
    )
    _write(
        config_dir / "standard_fields.yaml",
        """
        standard_only: true
        shared: standard
        """,
    )
    _write(
        config_dir / "shipping.yaml",
        """
        shipping_only: true
        shared: shipping
        """,
    )
    _write(
        config_dir / "attribute_rules.yaml",
        """
        attribute_only: true
        shared: attribute
        """,
    )

    monkeypatch.chdir(tmp_path)
    config = upload_command.load_config()

    assert "fiscal_only" not in config
    assert config["standard_only"] is True
    assert config["shipping_only"] is True
    assert config["attribute_only"] is True
    assert config["shared"] == "attribute"


def test_shipping_config_uses_defaults_when_split_missing_section(
    monkeypatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write(
        config_dir / "standard_fields.yaml",
        """
        shipping:
          mode_priority: ["me1", "me2"]
          default_mode: "me1"
        """,
    )
    _write(config_dir / "shipping.yaml", "feature_flag: true")

    monkeypatch.chdir(tmp_path)
    resolver = shipping_resolver.ShippingResolver(
        _ShippingProvider(
            user_info={"id": 123, "shipping_modes": ["me1", "me2"]},
            shipping_preferences={"modes": ["me1", "me2"]},
        )
    )

    assert resolver.mode_priority == ["me2", "me1"]
    assert resolver.default_mode == "not_specified"
    assert resolver.get_best_shipping_mode() == "me2"


def test_sanitizer_uses_split_keys_only(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write(
        config_dir / "standard_fields.yaml",
        """
        protected_attributes: ["GTIN", "ISBN"]
        similarity:
          redundancy_threshold: 0.77
        """,
    )
    _write(
        config_dir / "attribute_rules.yaml",
        """
        protected_attributes: ["HEIGHT"]
        similarity:
          redundancy_threshold: 0.91
        """,
    )

    monkeypatch.chdir(tmp_path)
    sanitizer = sanitizer_module.AttributeSanitizer()

    assert sanitizer.protected_attributes == {"HEIGHT"}
    assert sanitizer.similarity_threshold == 0.91
