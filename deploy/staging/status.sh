#!/usr/bin/env bash
set -Eeuo pipefail

STATE_ROOT=/opt/neomarket-staging
ROOT="$STATE_ROOT/compose"
SECRETS=/etc/neomarket/staging.env
RELEASE_ENV="$STATE_ROOT/.release.env"
COMPOSE=(docker compose --project-name neomarket-staging --env-file "$SECRETS" --env-file "$RELEASE_ENV" -f "$ROOT/docker-compose.staging.yml")

if [[ -f /etc/neomarket/registry-docker-config/config.json ]]; then
  export DOCKER_CONFIG=/etc/neomarket/registry-docker-config
fi

printf '%s\n' '=== compose status ==='
"${COMPOSE[@]}" ps --all
printf '%s\n' '=== health states ==='
for service in admin admin-worker b2b b2c gateway; do
  id="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"
  if [[ -z "$id" ]]; then
    printf '%s\n' "$service: missing"
    continue
  fi
  docker inspect --format '{{.Name}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}}' "$id"
done
printf '%s\n' '=== recent admin-worker logs ==='
"${COMPOSE[@]}" logs --no-color --tail=120 admin-worker 2>&1 || true
printf '%s\n' '=== recent admin/b2b logs ==='
"${COMPOSE[@]}" logs --no-color --tail=40 admin b2b 2>&1 || true
