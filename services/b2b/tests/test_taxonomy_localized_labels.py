import pytest
from pydantic import ValidationError

from src.schemas.admin_taxonomy import CategoryCreatePayload, CategoryUpdatePayload


def test_category_labels_trim_names_and_accept_locale_tags() -> None:
    payload = CategoryCreatePayload(
        code="chairs",
        slug="chairs",
        name="Furniture",
        labels={" ru-RU ": " Мебель ", "en-US": " Furniture "},
    )

    assert payload.labels == {"ru-RU": "Мебель", "en-US": "Furniture"}


@pytest.mark.parametrize(
    "labels",
    [
        {"en_US": "Furniture"},
        {"en-US": " "},
        {"en-US": "Furniture", "EN-us": "Мебель"},
        {"en-US": "x" * 256},
    ],
)
def test_category_labels_reject_invalid_locale_or_value(labels: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        CategoryUpdatePayload(labels=labels)


def test_category_labels_can_be_cleared_explicitly() -> None:
    assert CategoryUpdatePayload.model_validate({"labels": {}}).labels == {}
