#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/neomarket-staging
STATE=/var/lib/neomarket-staging
ETC=/etc/neomarket
DEPLOY_USER=neomarket-deploy
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat >&2 <<'EOF'
Usage: bootstrap.sh --registry-image ghcr.io/owner/repository --authorized-key-file FILE [--registry-username USER --registry-token-file FILE]
EOF
  exit 2
}

REGISTRY_IMAGE=''
AUTHORIZED_KEY_FILE=''
REGISTRY_USERNAME=''
REGISTRY_TOKEN_FILE=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry-image)
      [[ $# -ge 2 ]] || usage
      REGISTRY_IMAGE="$2"
      shift 2
      ;;
    --authorized-key-file)
      [[ $# -ge 2 ]] || usage
      AUTHORIZED_KEY_FILE="$2"
      shift 2
      ;;
    --registry-username)
      [[ $# -ge 2 ]] || usage
      REGISTRY_USERNAME="$2"
      shift 2
      ;;
    --registry-token-file)
      [[ $# -ge 2 ]] || usage
      REGISTRY_TOKEN_FILE="$2"
      shift 2
      ;;
    *) usage ;;
  esac
done

[[ "$EUID" -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ "$REGISTRY_IMAGE" =~ ^ghcr\.io/[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*$ ]] || { echo 'Invalid registry image prefix.' >&2; exit 1; }
[[ -r "$AUTHORIZED_KEY_FILE" ]] || { echo 'Authorized public key file is not readable.' >&2; exit 1; }
if [[ -n "$REGISTRY_USERNAME$REGISTRY_TOKEN_FILE" ]]; then
  [[ -n "$REGISTRY_USERNAME" && -n "$REGISTRY_TOKEN_FILE" ]] || { echo 'Registry username and token file must be supplied together.' >&2; exit 1; }
  [[ "$REGISTRY_USERNAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$ ]] || { echo 'Invalid registry username.' >&2; exit 1; }
  [[ -f "$REGISTRY_TOKEN_FILE" && -r "$REGISTRY_TOKEN_FILE" ]] || { echo 'Registry token file is not readable.' >&2; exit 1; }
  [[ "$(wc -l < "$REGISTRY_TOKEN_FILE")" -le 1 ]] || { echo 'Registry token file must contain one line.' >&2; exit 1; }
fi
KEY_LINE="$(tr -d '\r' < "$AUTHORIZED_KEY_FILE" | head -n 1)"
[[ "$KEY_LINE" =~ ^ssh-(ed25519|rsa|ecdsa-sha2-nistp256)[[:space:]] ]] || { echo 'Only an SSH public key is accepted.' >&2; exit 1; }
KEY_LINE_COUNT="$(tr -d '\r' < "$AUTHORIZED_KEY_FILE" | awk 'NF {count++} END {print count + 0}')"
[[ "$KEY_LINE_COUNT" == '1' ]] || { echo 'Public key must contain exactly one non-empty line.' >&2; exit 1; }

if [[ -e "$ROOT" && ! -f "$ROOT/metadata/bootstrap.manifest" ]]; then
  echo "Refusing to adopt existing unmarked path $ROOT." >&2
  exit 1
fi

for f in docker-compose.staging.yml nginx.conf init.sql deploy.sh smoke.sh status.sh prepare_admin_db_isolation.py bootstrap_secrets.py; do
  [[ -f "$SOURCE_ROOT/$f" ]] || { echo "Missing source manifest $SOURCE_ROOT/$f" >&2; exit 1; }
done
[[ -f "$SOURCE_ROOT/keycloak/realm.template.json" ]] || { echo "Missing Keycloak realm template" >&2; exit 1; }

if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$STATE" --shell /bin/bash "$DEPLOY_USER"
fi
install -d -o root -g root -m 0755 "$ROOT" "$ROOT/compose" "$ROOT/metadata"
install -d -o root -g root -m 0750 "$ROOT/compose/keycloak"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$STATE" "$STATE/requests" "$STATE/.ssh"
install -d -o root -g root -m 0750 /var/log/neomarket-staging
install -d -o root -g root -m 0750 "$ETC"

for f in docker-compose.staging.yml nginx.conf init.sql deploy.sh smoke.sh prepare_admin_db_isolation.py bootstrap_secrets.py; do
  install -o root -g root -m 0644 "$SOURCE_ROOT/$f" "$ROOT/compose/$f"
done
install -o root -g root -m 0755 "$SCRIPT_DIR/complete_test_secrets.py" "$ROOT/compose/complete_test_secrets.py"
install -o root -g root -m 0755 "$SCRIPT_DIR/prepare_keycloak_realm.py" "$ROOT/compose/prepare_keycloak_realm.py"
install -o root -g root -m 0640 "$SOURCE_ROOT/keycloak/realm.template.json" "$ROOT/compose/keycloak/realm.template.json"
chmod 0755 "$ROOT/compose/deploy.sh" "$ROOT/compose/smoke.sh" "$ROOT/compose/status.sh"
printf 'REGISTRY_IMAGE=%s\n' "$REGISTRY_IMAGE" > "$ETC/staging-release.conf"
chown root:root "$ETC/staging-release.conf"
chmod 0640 "$ETC/staging-release.conf"

if [[ -n "$REGISTRY_TOKEN_FILE" ]]; then
  REGISTRY_DOCKER_CONFIG="$ETC/registry-docker-config"
  install -d -o root -g root -m 0700 "$REGISTRY_DOCKER_CONFIG"
  printf '%s\n' "$(tr -d '\r\n' < "$REGISTRY_TOKEN_FILE")" \
    | docker --config "$REGISTRY_DOCKER_CONFIG" login ghcr.io \
        --username "$REGISTRY_USERNAME" --password-stdin >/dev/null
  chmod 0600 "$REGISTRY_DOCKER_CONFIG/config.json"
  echo 'Configured root-only GHCR pull credentials.'
fi

install -o root -g root -m 0755 "$SCRIPT_DIR/neomarket-staging-deploy" /usr/local/sbin/neomarket-staging-deploy
install -o root -g root -m 0755 "$SCRIPT_DIR/neomarket-staging-status" /usr/local/sbin/neomarket-staging-status
install -o root -g root -m 0755 "$SCRIPT_DIR/neomarket-staging-ssh-guard" /usr/local/sbin/neomarket-staging-ssh-guard
install -o root -g root -m 0644 "$SCRIPT_DIR/neomarket-staging-deploy.sudoers" /etc/sudoers.d/neomarket-staging-deploy
chmod 0440 /etc/sudoers.d/neomarket-staging-deploy

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$STATE/.ssh"
printf 'command="/usr/local/sbin/neomarket-staging-ssh-guard",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty %s\n' "$KEY_LINE" > "$STATE/.ssh/authorized_keys"
chown "$DEPLOY_USER":"$DEPLOY_USER" "$STATE/.ssh/authorized_keys"
chmod 0600 "$STATE/.ssh/authorized_keys"

printf 'REGISTRY_IMAGE=%s\nBOOTSTRAP_SOURCE_SHA256=%s\n' \
  "$REGISTRY_IMAGE" "$(sha256sum "$SOURCE_ROOT/docker-compose.staging.yml" | awk '{print $1}')" \
  > "$ROOT/metadata/bootstrap.manifest"
chown root:root "$ROOT/metadata/bootstrap.manifest"
chmod 0644 "$ROOT/metadata/bootstrap.manifest"

# Keep the one-time privileged step deterministic for staging. The base helper
# intentionally refuses to overwrite an existing env file; skip it on refresh
# and let the additive helper fill only missing test/provider values.
if [[ ! -e "$ETC/staging.env" ]]; then
  python3 "$ROOT/compose/bootstrap_secrets.py"
fi
# This helper is additive and safe on refreshes.
python3 "$ROOT/compose/complete_test_secrets.py"

echo "Bootstrap installed at $ROOT for $DEPLOY_USER. Missing staging test secrets were generated once."
echo "Root-owned staging env is ready; deployment requests can now be submitted."
