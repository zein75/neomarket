from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_service_dockerfiles_use_non_root_runtime_user():
    for service in ("b2c", "b2b", "admin"):
        dockerfile = (ROOT / "services" / service / "Dockerfile").read_text(encoding="utf-8")
        assert "USER app" in dockerfile
        assert "uid 10001" in dockerfile
        assert "uv:latest" not in dockerfile


def test_production_services_drop_capabilities():
    compose = (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    assert compose.count('cap_drop: ["ALL"]') == 3
    assert compose.count('no-new-privileges:true') == 3
