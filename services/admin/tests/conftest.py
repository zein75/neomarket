import os
import sys
from pathlib import Path


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ADMIN_ALLOW_DEV_AUTH", "true")
os.environ.setdefault("OIDC_MFA_CLAIMS_CONFIGURED", "true")

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
