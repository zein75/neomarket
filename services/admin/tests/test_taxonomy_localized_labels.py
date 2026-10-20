import pytest
from pydantic import ValidationError

from src.schemas.taxonomy import CategoryInput, CategoryView


def test_category_input_preserves_localized_names() -> None:
    category = CategoryInput(
        code="chairs",
        slug="chairs",
        name="Furniture",
        labels={"ru-RU": " Мебель ", "en-US": " Furniture "},
    )

    assert category.labels == {"ru-RU": "Мебель", "en-US": "Furniture"}


def test_category_input_rejects_invalid_localized_name() -> None:
    with pytest.raises(ValidationError):
        CategoryInput(code="chairs", slug="chairs", name="Furniture", labels={"en_US": "Furniture"})


def test_category_response_defaults_labels_for_legacy_b2b_data() -> None:
    category = CategoryView.model_validate(
        {
            "id": "e5e84939-00e5-4050-8207-1a80f19c0194",
            "code": "chairs",
            "slug": "chairs",
            "name": "Furniture",
            "status": "ACTIVE",
            "version": 1,
        }
    )

    assert category.labels == {}
