from pathlib import Path

from src.models.inventory_ledger import InventoryLedger
from src.models.inventory_order_lifecycle import InventoryOrderLifecycle, ReservationLine


def test_inventory_lifecycle_models_declare_required_constraints() -> None:
    lifecycle_names = {c.name for c in InventoryOrderLifecycle.__table__.constraints if c.name}
    line_names = {c.name for c in ReservationLine.__table__.constraints if c.name}
    assert "ck_inventory_lifecycle_state" in lifecycle_names
    assert "ck_reservation_lines_quantity" in line_names
    assert "ck_reservation_lines_state" in line_names
    assert InventoryLedger.__table__.c.event_id.unique is True


def test_inventory_lifecycle_migration_exists() -> None:
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0019_inventory_lifecycle_ledger.py"
    assert path.exists()
    assert "inventory_order_lifecycle" in path.read_text(encoding="utf-8")
