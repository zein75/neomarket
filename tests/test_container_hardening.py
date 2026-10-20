from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP_SERVICES = ("admin", "admin-worker", "b2c", "b2c-recovery-worker", "b2b")


def test_service_dockerfiles_use_non_root_runtime_user():
    for service in ("b2c", "b2b", "admin"):
        dockerfile = (ROOT / "services" / service / "Dockerfile").read_text(encoding="utf-8")
        assert "USER app" in dockerfile
        assert "uid 10001" in dockerfile
        assert "uv:latest" not in dockerfile


def test_production_services_drop_capabilities():
    compose = yaml.safe_load(
        (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    )
    for name in APP_SERVICES:
        service = compose["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
