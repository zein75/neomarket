#!/usr/bin/env bash
set -Eeuo pipefail

fail=0
require_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    printf 'PASS command %s=%s\n' "$1" "$(command -v "$1")"
  else
    printf 'FAIL missing command %s\n' "$1"
    fail=1
  fi
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo 'Run prerequisites as root.' >&2; exit 2; }
require_cmd install
require_cmd sha256sum
require_cmd openssl
require_cmd docker
require_cmd systemctl
require_cmd getent
require_cmd flock
require_cmd python3
require_cmd tee

docker info --format 'PASS docker server={{.ServerVersion}}' 2>&1 || fail=1
docker compose version 2>&1 || fail=1
systemctl is-active --quiet docker && echo 'PASS docker.service active' || { echo 'FAIL docker.service inactive'; fail=1; }

if getent passwd neomarket-deploy >/dev/null; then
  echo 'INFO neomarket-deploy already exists'
fi

if [[ "$fail" -ne 0 ]]; then
  echo 'Prerequisites failed.' >&2
  exit 1
fi
echo 'Prerequisites passed.'
