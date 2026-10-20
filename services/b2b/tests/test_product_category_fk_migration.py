from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "0058_product_category_fk.py"
)
SPEC = spec_from_file_location("product_category_fk_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class _Result:
    def __init__(self, *, rows=()):
        self.rows = rows

    def all(self):
        return self.rows


def test_upgrade_refuses_orphan_product_category_references(monkeypatch):
    connection = Mock()
    connection.execute.return_value = _Result(
        rows=[("product-id", "missing-category-id")]
    )
    create_foreign_key = Mock()
    monkeypatch.setattr(
        MIGRATION,
        "op",
        SimpleNamespace(get_bind=lambda: connection, create_foreign_key=create_foreign_key),
    )

    with pytest.raises(RuntimeError, match="orphan reference") as error:
        MIGRATION.upgrade()

    assert "missing-category-id" in str(error.value)
    create_foreign_key.assert_not_called()


def test_upgrade_adds_restricting_foreign_key_when_no_orphans(monkeypatch):
    connection = Mock()
    connection.execute.return_value = _Result(rows=[])
    create_foreign_key = Mock()
    monkeypatch.setattr(
        MIGRATION,
        "op",
        SimpleNamespace(get_bind=lambda: connection, create_foreign_key=create_foreign_key),
    )

    MIGRATION.upgrade()

    create_foreign_key.assert_called_once_with(
        "fk_products_category_id_categories",
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
