#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$#" -ne 2 || ! "$2" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: deploy.sh REGISTRY_IMAGE FULL_COMMIT_SHA" >&2
  exit 2
fi
umask 077
REGISTRY_IMAGE="$1"
RELEASE_SHA="$2"
ROOT=/opt/neomarket-staging
SECRETS=/etc/neomarket/staging.env
cd "$ROOT"
[[ -r "$SECRETS" ]] || { echo "missing secrets $SECRETS" >&2; exit 1; }
# The schema is mounted into the official postgres image and must be readable
# by its non-root postgres user; it contains no credentials.
chmod 0644 "$ROOT/init.sql"
chmod 0644 "$ROOT/nginx.conf"
# Check resources before first deployment. Allow override only for an explicitly accepted lab experiment.
if [[ "${ALLOW_LOW_MEMORY:-0}" != 1 ]]; then
  mem_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
  if (( mem_kb < 3800000 )); then
    echo "STOP: this full stack requires at least ~4GiB RAM; found ${mem_kb}KiB" >&2
    exit 1
  fi
fi
if (( $(df -Pk "$ROOT" | awk 'END{print $4}') < 8000000 )); then
  echo "STOP: less than ~8GiB available disk space" >&2
  exit 1
fi
PREVIOUS=""
if [[ -r .release.env ]]; then
  PREVIOUS="$(awk -F= '$1=="RELEASE_SHA" {print $2}' .release.env)"
fi
printf 'REGISTRY_IMAGE=%s\nRELEASE_SHA=%s\n' "$REGISTRY_IMAGE" "$RELEASE_SHA" > .release.env.tmp
mv .release.env.tmp .release.env
COMPOSE=(docker compose --project-name neomarket-staging --env-file "$SECRETS" --env-file "$ROOT/.release.env" -f "$ROOT/docker-compose.staging.yml")
"${COMPOSE[@]}" config --quiet
# Security gate: inspect EFFECTIVE publish rules, not just original YAML.
"${COMPOSE[@]}" config --format json | python3 -c '
import json,sys
services=json.load(sys.stdin)["services"]
for name, cfg in services.items():
  published=cfg.get("ports",[])
  if name != "gateway" and published:
    sys.exit("FATAL public port on " + name)
  for p in published:
    if p.get("host_ip") != "127.0.0.1" or str(p.get("published")) != "8080":
      sys.exit("FATAL unexpected gateway port binding: " + str(p))
print("Port exposure gate: PASS")
'
# Docker Compose: upgrade by pulling remotely built images, never building on the VPS.
"${COMPOSE[@]}" pull b2b b2c admin
"${COMPOSE[@]}" up -d --wait postgres redis
# Requires migrations to be backward compatible with currently running services.
"${COMPOSE[@]}" --profile migrate run --rm b2b-migrate
"${COMPOSE[@]}" --profile migrate run --rm b2c-migrate
"${COMPOSE[@]}" --profile migrate run --rm admin-migrate
"${COMPOSE[@]}" up -d --no-deps b2b b2c admin
"${COMPOSE[@]}" up -d --wait gateway
bash "$ROOT/smoke.sh"
printf '%s\n' "$RELEASE_SHA" > "$ROOT/last-successful-sha"
printf 'DEPLOY_SUCCESS sha=%s previous_sha=%s\n' "$RELEASE_SHA" "$PREVIOUS"
