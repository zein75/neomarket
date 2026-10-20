#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/neomarket-staging
STATE=/var/lib/neomarket-staging
DEPLOY_USER=neomarket-deploy

[[ "$EUID" -eq 0 ]] || { echo 'Run verify as root.' >&2; exit 1; }
id "$DEPLOY_USER" >/dev/null
[[ "$(stat -c '%U:%G %a' /usr/local/sbin/neomarket-staging-deploy)" == "root:root 755" ]]
[[ "$(stat -c '%U:%G %a' /etc/sudoers.d/neomarket-staging-deploy)" == "root:root 440" ]]
[[ "$(stat -c '%U:%G %a' "$STATE/.ssh/authorized_keys")" == "$DEPLOY_USER:$DEPLOY_USER 600" ]]
[[ -f "$ROOT/metadata/bootstrap.manifest" ]]
[[ ! -e /var/run/docker.sock || "$(stat -c '%U:%G' /var/run/docker.sock)" == 'root:docker' ]]
if getent group docker | grep -Eq "(^|:)${DEPLOY_USER}(,|$)"; then
  echo 'FAIL deployment user is in docker group' >&2
  exit 1
fi
visudo -cf /etc/sudoers >/dev/null
echo 'Staging bootstrap verification: PASS'
