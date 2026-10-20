from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from src.repositories.product_repo import ProductRepository


class _Result:
    def scalar_one(self) -> int:
        return 0

    def all(self) -> list[Any]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result()


@pytest.mark.asyncio
async def test_seller_search_treats_sql_injection_and_like_wildcards_as_data() -> None:
    session = _Session()
    payload = "%" + chr(39) + " OR 1=1 --_"

    rows, total = await ProductRepository(session).list_for_seller_cabinet(
        seller_id=uuid4(),
        limit=20,
        offset=0,
        search=payload,
    )

    assert rows == []
    assert total == 0
    compiled = session.statements[1].compile(dialect=postgresql.dialect())
    assert payload not in compiled.string
    search_params = [value for value in compiled.params.values() if isinstance(value, str)]
    assert len(search_params) == 2
    assert all(" OR 1=1" in value for value in search_params)
    assert all("/%" in value and "/_" in value for value in search_params)
