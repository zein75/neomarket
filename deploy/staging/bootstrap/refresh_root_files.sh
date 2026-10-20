#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$EUID" -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Prefer the checked-out staging manifests when this helper is run directly
# from deploy/staging/bootstrap. Keep the /tmp contract as a fallback for the
# already-installed root refresh workflow.
if [[ -f "$SOURCE_ROOT/docker-compose.staging.yml" && \
      -f "$SOURCE_ROOT/status.sh" && \
      -f "$SOURCE_ROOT/Caddyfile" && \
      -f "$SOURCE_ROOT/nginx.conf" ]]; then
  COMPOSE_SRC="$SOURCE_ROOT/docker-compose.staging.yml"
  STATUS_SRC="$SOURCE_ROOT/status.sh"
  CADDY_SRC="$SOURCE_ROOT/Caddyfile"
  NGINX_SRC="$SOURCE_ROOT/nginx.conf"
else
  COMPOSE_SRC=/tmp/ter0o-neomarket-compose.yml
  STATUS_SRC=/tmp/ter0o-neomarket-status.sh
  CADDY_SRC=/tmp/ter0o-neomarket-Caddyfile
  NGINX_SRC=/tmp/ter0o-neomarket-nginx.conf
fi
COMPOSE_DST=/opt/neomarket-staging/compose/docker-compose.staging.yml
STATUS_DST=/opt/neomarket-staging/compose/status.sh
NGINX_DST=/opt/neomarket-staging/compose/nginx.conf
CADDY_DST=/etc/caddy/Caddyfile
DEPLOY_WRAPPER_SRC="$SOURCE_ROOT/bootstrap/neomarket-staging-deploy"

for path in "$COMPOSE_SRC" "$STATUS_SRC" "$CADDY_SRC" "$NGINX_SRC"; do
  [[ -f "$path" ]] || { echo "Missing $path" >&2; exit 1; }
done

caddy validate --config "$CADDY_SRC" --adapter caddyfile
backup="$CADDY_DST.neomarket.backup.$(date +%Y%m%d%H%M%S)"
cp -a "$CADDY_DST" "$backup"
install -o root -g root -m 0644 "$CADDY_SRC" "$CADDY_DST"
install -o root -g root -m 0644 "$COMPOSE_SRC" "$COMPOSE_DST"
install -o root -g root -m 0755 "$STATUS_SRC" "$STATUS_DST"
install -o root -g root -m 0644 "$NGINX_SRC" "$NGINX_DST"
if [[ -f "$DEPLOY_WRAPPER_SRC" ]]; then
  install -o root -g root -m 0755 "$DEPLOY_WRAPPER_SRC" /usr/local/sbin/neomarket-staging-deploy
fi
systemctl reload caddy
rm -f "$COMPOSE_SRC" "$STATUS_SRC" "$CADDY_SRC" "$NGINX_SRC"
echo "Installed staging Compose, diagnostics and Caddy configuration. Backup: $backup"
