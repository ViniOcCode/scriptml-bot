from mercadolivre_upload.infrastructure.migration import Field, FieldType, SchemaVersion


def _build_schema() -> SchemaVersion:
    return SchemaVersion(
        "1.0",
        fields={
            "sku": Field("sku", FieldType.STRING, required=True, aliases=["codigo"]),
            "price": Field("price", FieldType.DECIMAL, aliases=["preco"]),
        },
    )


def test_has_field_considers_aliases() -> None:
    schema = _build_schema()

    assert schema.has_field("sku") is True
    assert schema.has_field("codigo") is True
    assert schema.has_field("inexistente") is False


def test_get_field_by_name_returns_field_for_alias() -> None:
    schema = _build_schema()

    field = schema.get_field_by_name("preco")

    assert field is not None
    assert field.name == "price"


def test_validate_data_reports_required_and_type_errors() -> None:
    schema = _build_schema()

    errors = schema.validate_data({"price": "abc"})

    assert "Campo obrigatório ausente: sku" in errors
    assert any("Tipo inválido para 'price': esperado DECIMAL" in err for err in errors)
