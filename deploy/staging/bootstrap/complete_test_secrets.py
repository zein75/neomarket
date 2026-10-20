#!/usr/bin/env python3
"""Add only missing generated test secrets to the root-owned staging env."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

DEST = Path("/etc/neomarket/staging.env")
if os.geteuid() != 0:
    raise SystemExit("Run as root: sudo python3 complete_test_secrets.py")
if not DEST.exists():
    raise SystemExit(f"Missing {DEST}; run bootstrap_secrets.py first")

lines = DEST.read_text(encoding="utf-8").splitlines()
present = {line.split("=", 1)[0] for line in lines if line and not line.startswith("#") and "=" in line}
generated = {
    "MEDIA_UPLOAD_SIGNING_SECRET": secrets.token_hex(48),
    "KEYCLOAK_DB_PASSWORD": secrets.token_hex(32),
    "KEYCLOAK_ADMIN_USERNAME": "kc-admin",
    "KEYCLOAK_ADMIN_PASSWORD": secrets.token_urlsafe(32),
    "KEYCLOAK_TEST_USER_PASSWORD": secrets.token_urlsafe(24),
    "ADMIN_OIDC_CLIENT_SECRET": secrets.token_urlsafe(32),
}
configured = {
    "ADMIN_PUBLIC_ORIGIN": "https://admin.neomarket.test",
    "STOREFRONT_PUBLIC_ORIGIN": "https://storefront.neomarket.test",
    "SELLER_PUBLIC_ORIGIN": "https://seller.neomarket.test",
    "ADMIN_OIDC_ISSUER": "https://keycloak.neomarket.test/realms/neomarket-staging",
    "ADMIN_OIDC_JWKS_URL": "https://keycloak.neomarket.test/realms/neomarket-staging/protocol/openid-connect/certs",
    "ADMIN_OIDC_AUDIENCE": "neomarket-admin",
    "ADMIN_OIDC_CLIENT_ID": "neomarket-admin-bff",
    "ADMIN_OIDC_REQUIRED_AMR": "otp",
    "ADMIN_OIDC_STEP_UP_REQUIRED_AMR": "otp",
    "SELLER_EMAIL_SMTP_HOST": "mailpit",
    "SELLER_EMAIL_SMTP_PORT": "1025",
    "SELLER_EMAIL_SMTP_MODE": "starttls",
    "SELLER_EMAIL_FROM_ADDRESS": "no-reply@neomarket.test",
    "SELLER_VERIFICATION_URL": "https://seller.neomarket.test/verify-email",
    "SELLER_INVITATION_URL": "https://seller.neomarket.test/team/accept-invite",
    "MEDIA_PUBLIC_BASE_URL": "https://seller.neomarket.test/api/v1/media/public",
}
generated.update(configured)
missing = [f"{key}={value}" for key, value in generated.items() if key not in present]
if missing:
    with DEST.open("a", encoding="utf-8") as file:
        file.write("\n" + "\n".join(missing) + "\n")
    os.chmod(DEST, 0o640)
    print(f"Added {len(missing)} generated staging secret(s) to {DEST}")
else:
    print(f"No generated staging secrets missing from {DEST}")
