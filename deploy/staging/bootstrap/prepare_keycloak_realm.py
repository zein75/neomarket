#!/usr/bin/env python3
"""Render the root-owned Keycloak realm from generated staging secrets."""
from __future__ import annotations

import os
from pathlib import Path

if os.geteuid() != 0:
    raise SystemExit("Run as root")

root = Path("/opt/neomarket-staging/compose")
template = root / "keycloak" / "realm.template.json"
target = root / "keycloak" / "realm.json"
env_path = Path("/etc/neomarket/staging.env")
if not template.exists():
    raise SystemExit(f"Missing {template}")
values = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("\"'")
required = ("ADMIN_OIDC_CLIENT_SECRET", "KEYCLOAK_TEST_USER_PASSWORD")
missing = [key for key in required if not values.get(key)]
if missing:
    raise SystemExit("Missing generated Keycloak values: " + ", ".join(missing))
text = template.read_text(encoding="utf-8")
for key in required:
    text = text.replace("{{" + key + "}}", values[key])
target.write_text(text, encoding="utf-8")
os.chmod(target, 0o640)
print(f"Rendered {target}")
