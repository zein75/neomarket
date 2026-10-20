import asyncio
from types import SimpleNamespace
from uuid import uuid4

from starlette.responses import Response

from src.api.routers import taxonomy
from src.clients.b2b_client import B2BClient


def test_admin_category_registry_maps_the_authoritative_b2b_snapshot(monkeypatch):
    category_id = uuid4()
    parent_id = uuid4()

    async def get_internal_json(_self, path):
        assert path == '/internal/v1/taxonomy/snapshot'
        return {
            'version': 9,
            'categories': [{
                'id': str(category_id), 'parent_id': str(parent_id), 'code': 'office',
                'slug': 'office', 'name': 'Office', 'description': None, 'status': 'ACTIVE',
                'sort_order': 1, 'version': 3, 'path': '/catalog/office', 'seo_title': None,
                'image_media_id': None, 'schema_version': 0, 'attribute_rules': [],
                'updated_at': '2026-10-18T12:00:00Z',
            }],
            'attributes': [],
            'as_of': '2026-10-18T12:00:00Z',
        }

    monkeypatch.setattr(B2BClient, 'get_internal_json', get_internal_json)
    result = asyncio.run(taxonomy.list_categories(_=SimpleNamespace(id=uuid4())))

    assert result.taxonomy_version == 9
    assert result.items[0].id == category_id
    assert result.items[0].parent_id == parent_id
    assert result.items[0].status == 'ACTIVE'
    assert result.items[0].path == '/catalog/office'


def test_admin_schema_preview_uses_inherited_rules_and_child_overrides():
    root_id, child_id, attribute_id, other_attribute_id = (uuid4() for _ in range(4))
    snapshot = {
        'categories': [
            {'id': str(root_id), 'parent_id': None, 'schema_version': 1, 'attribute_rules': [
                {'attribute_id': str(attribute_id), 'required': True},
                {'attribute_id': str(other_attribute_id), 'required': True},
            ]},
            {'id': str(child_id), 'parent_id': str(root_id), 'schema_version': 1, 'attribute_rules': [
                {'attribute_id': str(attribute_id), 'required': False},
            ]},
        ]
    }

    rules, published = taxonomy._effective_category_rules(snapshot, child_id)

    assert published is True
    assert {rule.attribute_id: rule.required for rule in rules} == {
        attribute_id: False,
        other_attribute_id: True,
    }


def test_new_category_exposes_empty_rule_set_at_schema_version_zero(monkeypatch):
    category_id = uuid4()

    async def get_internal_json(_self, path):
        assert path == '/internal/v1/taxonomy/snapshot'
        return {
            'version': 1,
            'categories': [{
                'id': str(category_id), 'parent_id': None, 'code': 'draft', 'slug': 'draft',
                'name': 'Draft', 'status': 'DRAFT', 'version': 1, 'schema_version': 0,
                'attribute_rules': [],
            }],
            'attributes': [],
        }

    monkeypatch.setattr(B2BClient, 'get_internal_json', get_internal_json)
    result = asyncio.run(taxonomy.get_category_rules(category_id, _=SimpleNamespace(id=uuid4())))

    assert result.items == []
    assert result.schema_version == 0


def test_large_taxonomy_impact_preview_proxies_accepted_job(monkeypatch):
    category_id, parent_id, job_id = (uuid4() for _ in range(3))

    async def snapshot():
        return {"categories": [{"id": str(category_id), "version": 4}]}

    async def post_internal_json(_self, path, body, *, idempotency_key, if_match):
        assert path == f"/internal/v1/taxonomy/categories/{category_id}/impact-preview"
        assert body == {"change_type": "MOVE", "new_parent_id": str(parent_id)}
        assert idempotency_key == str(job_id)
        assert if_match == '"4"'
        return {
            "job_id": str(job_id), "status": "QUEUED", "stage": "CATEGORIES",
            "processed_categories": 0, "total_categories": 5001,
            "processed_products": 0, "total_products": 0, "error_code": None, "result": None,
        }

    monkeypatch.setattr(taxonomy, "_snapshot", snapshot)
    monkeypatch.setattr(B2BClient, "post_internal_json", post_internal_json)
    response = Response()
    result = asyncio.run(taxonomy.preview_category_impact(
        category_id,
        taxonomy.ImpactPreviewInput(change_type="MOVE", new_parent_id=parent_id),
        response,
        job_id,
        SimpleNamespace(id=uuid4()),
    ))

    assert response.status_code == 202
    assert result["job_id"] == str(job_id)
    assert result["status"] == "QUEUED"


def test_taxonomy_impact_job_status_is_proxied_and_validated(monkeypatch):
    job_id = uuid4()

    async def get_internal_json(_self, path):
        assert path == f"/internal/v1/taxonomy/impact-preview-jobs/{job_id}"
        return {
            "job_id": str(job_id), "status": "RUNNING", "stage": "PRODUCTS",
            "processed_categories": 5001, "total_categories": 5001,
            "processed_products": 200, "total_products": 1400, "error_code": None, "result": None,
        }

    monkeypatch.setattr(B2BClient, "get_internal_json", get_internal_json)
    result = asyncio.run(taxonomy.get_taxonomy_impact_job(job_id, SimpleNamespace(id=uuid4())))

    assert result["job_id"] == str(job_id)
    assert result["stage"] == "PRODUCTS"
    assert result["processed_products"] == 200
