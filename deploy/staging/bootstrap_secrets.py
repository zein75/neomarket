"""Run as root once on the VPS: sudo python3 bootstrap_secrets.py

Requires openssl. Never put the generated secrets into source control or CI logs.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess

DEST = Path('/etc/neomarket/staging.env')
if os.geteuid() != 0:
    raise SystemExit('Run as root: sudo python3 bootstrap_secrets.py')
if DEST.exists():
    raise SystemExit(f'{DEST} already exists; refusing to overwrite live secrets')
DEST.parent.mkdir(parents=True, exist_ok=True)
keys = {}
pubs = {}
for service in ('b2b', 'b2c', 'admin'):
    private = subprocess.check_output(
        ['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072'],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    public = subprocess.check_output(
        ['openssl', 'pkey', '-pubout'],
        input=private,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    keys[service] = private
    pubs[f'{service}-v1'] = public

pairs = {
    'POSTGRES_PASSWORD': secrets.token_hex(32),
    'REDIS_PASSWORD': secrets.token_hex(32),
    'B2B_SECRET_KEY': secrets.token_hex(48),
    'B2C_SECRET_KEY': secrets.token_hex(48),
    'ADMIN_SECRET_KEY': secrets.token_hex(48),
    'SERVICE_KEY': secrets.token_hex(48),
}
content = [f'{k}={v}' for k, v in pairs.items()]
for s in ('b2b','b2c','admin'):
    # Compose double-quoted .env interprets escaped newlines as real newlines.
    content.append(f'{s.upper()}_SERVICE_PRIVATE_KEY={json.dumps(keys[s])}')
# Preserve JSON escaping for PEM newlines by surrounding with single quotes.
content.append("TRUSTED_SERVICE_PUBLIC_KEYS='" + json.dumps(pubs, separators=(',', ':')) + "'")
fd = os.open(DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
with os.fdopen(fd, 'w', encoding='utf-8') as file:
    file.write('\n'.join(content) + '\n')
os.chmod(DEST, 0o640)
print(f'Created {DEST}. Ensure its group is the staging deploy group; NEVER print its content.')
