from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.schemas.product import ProductDraftCreate


def _payload(count: int) -> dict[str, object]:
    return {
        "title": "Industrial controller",
        "description": "Draft with validated variants",
        "category_id": str(uuid4()),
        "attributes": {"manufacturer": "ExampleCo"},
        "media_ids": [],
        "variants": [
            {
                "seller_article": f"CTRL-{index:03}",
                "name": f"Controller variant {index}",
                "price_minor": 12_345 + index,
                "currency": "RUB",
                "on_hand": index,
                "options": {"color": f"color-{index}"},
            }
            for index in range(count)
        ],
    }


def test_product_draft_accepts_twenty_and_contract_maximum_variants() -> None:
    twenty = ProductDraftCreate.model_validate(_payload(20))
    maximum = ProductDraftCreate.model_validate(_payload(100))

    assert len(twenty.variants) == 20
    assert len(maximum.variants) == 100


@pytest.mark.parametrize("count", [0, 101])
def test_product_draft_rejects_variant_counts_outside_contract(count: int) -> None:
    with pytest.raises(ValidationError):
        ProductDraftCreate.model_validate(_payload(count))


def test_product_draft_rejects_case_insensitive_duplicate_articles() -> None:
    payload = _payload(2)
    payload["variants"][1]["seller_article"] = payload["variants"][0]["seller_article"].lower()

    with pytest.raises(ValidationError, match="unique within the batch"):
        ProductDraftCreate.model_validate(payload)


def test_product_draft_rejects_invalid_variant_before_persistence() -> None:
    payload = _payload(20)
    payload["variants"][13]["price_minor"] = -1

    with pytest.raises(ValidationError):
        ProductDraftCreate.model_validate(payload)


def test_product_draft_rejects_mixed_currency_and_signed_64_bit_overflow() -> None:
    mixed = _payload(2)
    mixed["variants"][1]["currency"] = "USD"
    with pytest.raises(ValidationError, match="same currency"):
        ProductDraftCreate.model_validate(mixed)

    overflow = _payload(1)
    overflow["variants"][0]["price_minor"] = 9_223_372_036_854_775_808
    with pytest.raises(ValidationError):
        ProductDraftCreate.model_validate(overflow)
