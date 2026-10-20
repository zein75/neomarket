from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "deploy" / "staging" / "nginx.conf"
REFRESH = ROOT / "deploy" / "staging" / "bootstrap" / "refresh_root_files.sh"
DEPLOY = ROOT / "deploy" / "staging" / "bootstrap" / "neomarket-staging-deploy"


def _server_block(config: str, server_name: str) -> str:
    marker = f"server_name {server_name};"
    start = config.index(marker)
    start = config.rfind("server {", 0, start)
    end = config.index("\n    }", start)
    return config[start:end]


def test_frontend_hosts_route_to_their_own_upstreams() -> None:
    config = NGINX.read_text(encoding="utf-8")

    assert "proxy_pass http://storefront;" in _server_block(
        config, "storefront.internal storefront.neomarket.test"
    )
    assert "proxy_pass http://seller_frontend;" in _server_block(
        config, "seller.internal seller.neomarket.test"
    )
    assert "proxy_pass http://admin_frontend;" in _server_block(
        config, "admin.internal admin.neomarket.test"
    )


def test_root_refresh_and_deploy_reload_gateway_config() -> None:
    refresh = REFRESH.read_text(encoding="utf-8")
    deploy = DEPLOY.read_text(encoding="utf-8")

    assert "NGINX_SRC=/tmp/ter0o-neomarket-nginx.conf" in refresh
    assert "NGINX_DST=/opt/neomarket-staging/compose/nginx.conf" in refresh
    assert "--force-recreate gateway" in deploy
