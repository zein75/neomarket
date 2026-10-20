#!/usr/bin/env bash
set -Eeuo pipefail
STATE_ROOT=/opt/neomarket-staging
ROOT="$STATE_ROOT/compose"
cd "$ROOT"
SECRETS=/etc/neomarket/staging.env
COMPOSE=(docker compose --project-name neomarket-staging --env-file "$SECRETS" --env-file "$STATE_ROOT/.release.env" -f "$ROOT/docker-compose.staging.yml")
"${COMPOSE[@]}" ps
for component in b2b b2c admin gateway; do
  container_id="$("${COMPOSE[@]}" ps -q "$component")"
  [[ -n "$container_id" ]] || { echo "MISSING: $component" >&2; exit 1; }
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  [[ "$status" == healthy ]] || { echo "UNHEALTHY: $component=$status" >&2; exit 1; }
done
curl --fail --silent --show-error --max-time 5 -H 'Host: b2c.internal' http://127.0.0.1:18080/health
curl --fail --silent --show-error --max-time 5 -H 'Host: b2b.internal' http://127.0.0.1:18080/health

# Verify that each public frontend hostname reaches its own application. This
# catches a stale bind-mounted nginx.conf before a release is reported healthy.
check_frontend_route() {
  local host="$1" expected="$2" response
  response="$(curl --fail --silent --show-error --max-time 5 \
    -H "Host: $host" http://127.0.0.1:18080/api/health)"
  [[ "$response" == *"$expected"* ]] || {
    echo "FRONTEND ROUTE MISMATCH: $host returned $response (expected $expected)" >&2
    exit 1
  }
}
check_frontend_route storefront.neomarket.test '"status":"ok"'
check_frontend_route seller.neomarket.test '"service":"seller"'
check_frontend_route admin.neomarket.test '"service":"admin"'

# Staging negative security test. Internal endpoints MUST NOT cross the gateway.
for host in b2b.internal b2c.internal; do
  response="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $host" http://127.0.0.1:18080/internal/v1/inventory/orders/00000000-0000-0000-0000-000000000000)"
  [[ "$response" == 404 ]] || { echo "INTERNAL LEAK: $host returned $response" >&2; exit 1; }
done
printf '\nSMOKE PASS\n'
