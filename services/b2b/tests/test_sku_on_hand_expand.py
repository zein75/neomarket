from pathlib import Path

from src.models.sku import SKU


def test_sku_has_expand_on_hand_column():
    assert "on_hand" in SKU.__table__.c


def test_on_hand_migration_backfills_stock():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0020_sku_on_hand_expand.py"
    text = path.read_text(encoding="utf-8")
    assert "UPDATE skus SET on_hand = stock" in text
    assert "ck_skus_on_hand_nonnegative" in text
