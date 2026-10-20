# NeoMarket staging bootstrap

This bootstrap prepares a dedicated, non-root deployment account and a
root-owned staging runtime. It does not change Caddy, Nginx, SSH policy for
existing users, firewall rules, or existing Docker volumes.

The owner runs `bootstrap.sh` once from this directory as root. The script
installs a fixed deployment wrapper and a forced-command SSH key for
`neomarket-deploy`. That account can submit only a 40-character release SHA;
it cannot run Docker, arbitrary shell, `sudo`, or `systemctl` commands.

The bootstrap creates only missing staging test secrets and provider values. It
refuses to overwrite an existing env file or existing keys. No production
credentials are used.

## One-time owner command

```bash
cd /tmp/neomarket-staging-release/staging/bootstrap
sudo bash ./bootstrap.sh \
  --registry-image ghcr.io/zein75/market \
  --authorized-key-file /tmp/neomarket-staging-release/neomarket_staging_ci.pub
sudo ./verify.sh
```

For private GHCR packages, provide a read-only package token through the
server's protected secret mechanism (never through chat), then add:

```bash
  --registry-username zein75 \
  --registry-token-file /etc/neomarket/secrets/ghcr-read-token
```

The bootstrap stores it in a root-only Docker config and the deployment
wrapper uses that config for pulls.

`--registry-image` must be the exact lowercase GHCR image prefix used by the
protected staging workflow. The public key file is installed with a forced
command and forwarding disabled. Do not paste private keys or secret values
into Git or chat.

After this bootstrap, the CI workflow connects as `neomarket-deploy` and runs
only `neomarket-staging-request <sha>`. The root-owned wrapper validates the
SHA, uses the root-owned Compose manifest, pulls immutable SHA-tagged images,
runs migrations and smoke checks, and records the release SHA.

Infrastructure manifest changes require a separately reviewed bootstrap
refresh by the owner; CI cannot replace the root-owned Compose or deployment
scripts.
