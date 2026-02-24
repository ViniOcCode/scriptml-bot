"""Tests for structural attribute validation rules."""

from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.validation import StructuralValidator


def test_non_fillable_required_tags_do_not_block_missing_checks() -> None:
    validator = StructuralValidator(
        [
            AttributeMeta(id="VISIBLE_REQ", name="Visível", value_type="string", required=True),
            AttributeMeta(
                id="HIDDEN_REQ",
                name="Oculto",
                value_type="string",
                required=True,
                tags={"hidden"},
            ),
            AttributeMeta(
                id="READ_ONLY_REQ",
                name="Somente leitura",
                value_type="string",
                required=True,
                tags={"read_only"},
            ),
            AttributeMeta(
                id="LOCKED_REQ",
                name="Bloqueado",
                value_type="string",
                required=True,
                tags={"non-modifiable"},
            ),
        ]
    )

    result = validator.validate([{"id": "VISIBLE_REQ", "value_name": "ok"}])

    assert result.valid is True
    assert result.blocking_errors == []


def test_fillable_required_attribute_still_blocks_when_missing() -> None:
    validator = StructuralValidator(
        [AttributeMeta(id="BRAND", name="Marca", value_type="string", required=True)]
    )

    result = validator.validate([])

    assert result.valid is False
    assert result.blocking_errors == ["Missing required attribute 'BRAND'"]
