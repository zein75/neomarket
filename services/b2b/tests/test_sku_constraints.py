from pathlib import Path

from src.models.sku import SKU


def test_sku_model_declares_inventory_invariants() -> None:
    names = {
        constraint.name
        for constraint in SKU.__table__.constraints
        if constraint.name
    }
    assert names >= {
        "ck_skus_price_nonnegative",
        "ck_skus_stock_nonnegative",
        "ck_skus_reserved_nonnegative",
        "ck_skus_reserved_lte_stock",
    }


def test_inventory_constraints_have_a_migration() -> None:
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0018_sku_inventory_constraints.py"
    text = migration.read_text(encoding="utf-8")
    assert "ck_skus_reserved_lte_stock" in text
    assert "ck_skus_price_nonnegative" in text
