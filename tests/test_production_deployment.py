import json
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import yaml

from shared.utils.service_auth import service_headers, verify_service_token


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_LIMIT_SERVICES = (
    "admin",
    "admin-worker",
    "b2c",
    "b2c-recovery-worker",
    "b2b",
    "gateway",
)


def test_production_compose_is_separate_and_does_not_publish_internal_services():
    compose = (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")

    assert "gateway:" in compose
    assert '"80:80"' in compose
    for service in ("postgres", "redis", "admin", "b2c", "b2b"):
        section = compose.split(f"\n  {service}:\n", 1)[1]
        section = section.split("\n  ", 1)[0]
        assert "ports: []" in section


def test_prod_target_uses_production_override():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker-compose.prod.yaml" in makefile


def test_gateway_rejects_unknown_hosts_and_routes_named_services():
    config = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "return 444" in config
    assert "server_name b2c.internal" in config
    assert "server_name b2b.internal" in config


def test_production_healthchecks_use_readiness():
    compose = (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    assert compose.count("/ready") == 3
    assert 'test: ["CMD", "nginx", "-t"]' in compose


def test_production_services_have_resource_limits():
    compose = yaml.safe_load(
        (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    )
    for name in RESOURCE_LIMIT_SERVICES:
        limits = compose["services"][name]["deploy"]["resources"]["limits"]
        assert limits["cpus"]
        assert limits["memory"]
        assert limits["pids"] > 0


def test_production_backend_network_is_internal():
    compose = (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    assert "backend:" in compose
    assert "internal: true" in compose
    assert "networks: [backend, edge]" in compose


def test_gateway_has_request_size_and_security_headers():
    config = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "client_max_body_size 256k" in config
    assert 'X-Content-Type-Options "nosniff"' in config
    assert 'X-Frame-Options "DENY"' in config


def test_admin_worker_is_separate_and_inherits_deployment_identity_and_database():
    compose_files = (
        ROOT / "docker-compose.prod.yaml",
        ROOT / "deploy" / "staging" / "docker-compose.staging.yml",
    )
    for compose_path in compose_files:
        services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]
        api = services["admin"]
        worker = services["admin-worker"]
        api_env = api["environment"]
        worker_env = worker["environment"]

        worker_commands = [
            name
            for name, service in services.items()
            if "src.worker" in " ".join(service.get("command", []))
        ]
        assert worker_commands == ["admin-worker"]
        assert worker["image"] == api["image"]
        assert "src.worker" in " ".join(worker["command"])
        assert worker_env["ADMIN_RUN_OUTBOX_WORKER"] in ("true", True)
        assert api_env["ADMIN_RUN_OUTBOX_WORKER"] in ("false", False)
        for setting in (
            "DATABASE_URL",
            "SERVICE_PRIVATE_KEY",
            "TRUSTED_SERVICE_PUBLIC_KEYS",
            "SERVICE_KEY_ID",
            "APP_ENV",
            "ADMIN_ALLOW_DEV_AUTH",
        ):
            assert worker_env[setting] == api_env[setting]
        assert worker_env["SERVICE_NAME"] == "admin"
        assert not worker.get("ports")
        assert "b2b" in worker["depends_on"]

        healthcheck = " ".join(worker["healthcheck"]["test"])
        assert "/tmp/admin-worker-heartbeat" in healthcheck
        assert "updated_at" in healthcheck and "< 90" in healthcheck


def test_admin_service_token_subject_is_accepted_by_b2b_allow_list():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    issuer = SimpleNamespace(
        service_private_key=private_pem,
        service_name="admin",
        service_key_id="admin-v1",
        app_env="production",
        service_key="unused-local-fallback",
    )
    authorization = service_headers(issuer, audience="neomarket-b2b")["Authorization"]
    token = authorization.removeprefix("Bearer ")
    trusted_keys = json.dumps({"admin-v1": public_pem})

    assert verify_service_token(
        token,
        trusted_keys=trusted_keys,
        audience="neomarket-b2b",
        allowed_subjects={"admin"},
    )
    assert not verify_service_token(
        token,
        trusted_keys=trusted_keys,
        audience="neomarket-b2b",
        allowed_subjects={"b2c"},
    )


def test_gateway_has_edge_rate_limit_and_forwarded_request_context():
    config = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "limit_req_zone" in config
    assert "limit_req zone=api_rate" in config
    assert "X-Request-ID" in config
