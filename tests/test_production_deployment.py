from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    compose = (ROOT / "docker-compose.prod.yaml").read_text(encoding="utf-8")
    assert compose.count("resources:") == 4
    assert compose.count("memory:") == 4


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


def test_gateway_has_edge_rate_limit_and_forwarded_request_context():
    config = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "limit_req_zone" in config
    assert "limit_req zone=api_rate" in config
    assert "X-Request-ID" in config
