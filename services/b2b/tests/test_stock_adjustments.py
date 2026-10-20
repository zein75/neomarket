from pathlib import Path

from src.models.stock_adjustment import StockAdjustment


def test_stock_adjustment_is_auditable_and_nonzero() -> None:
    names = {c.name for c in StockAdjustment.__table__.constraints if c.name}
    assert "ck_stock_adjustments_delta_nonzero" in names
    assert "uq_stock_adjustments_seller_key" in names
    assert StockAdjustment.__table__.c.idempotency_key.unique is not True
    assert StockAdjustment.__table__.c.request_hash.type.length == 64
    assert StockAdjustment.__table__.c.result_on_hand is not None


def test_stock_adjustment_migration_exists() -> None:
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0021_stock_adjustments.py"
    assert path.exists()


def test_stock_adjustment_idempotency_migration_exists() -> None:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0029_stock_adjustment_idempotency.py"
    )
    assert path.exists()
