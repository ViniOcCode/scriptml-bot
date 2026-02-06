import pytest

from mercadolivre_upload.api.client import validate_item_id


class TestItemIdValidation:
    @pytest.mark.parametrize("valid_id", ["MLB123", "MLA9876543210", "MLC1"])
    def test_valid_ids_pass(self, valid_id):
        validate_item_id(valid_id)  # Não deve levantar

    @pytest.mark.parametrize(
        "invalid_id", ["", "123456", "MLB", "MLB-123", "mlb123", "ML123", "../MLB123"]
    )
    def test_invalid_ids_raise(self, invalid_id):
        with pytest.raises(ValueError):
            validate_item_id(invalid_id)
