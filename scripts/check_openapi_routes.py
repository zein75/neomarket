"""Compare current approved OpenAPI targets with the live FastAPI apps."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "admin-target.openapi.yaml": "services/admin",
    "b2b-admin-internal-target.openapi.yaml": "services/b2b",
}
CONTRACT_ROOT = ROOT / "docs/NeoMarket_Admin_Production_Spec_2026-10-16/contracts"
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def live_paths(service_root: str) -> dict[str, dict[str, dict[str, object]]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / service_root}{os.pathsep}{ROOT / 'shared'}"
    if service_root == "services/admin":
        # The checker must be hermetic even when the runner exports a staging
        # or production APP_ENV.  Supply all values needed by Settings before
        # importing the app so OpenAPI generation never depends on host env.
        env.update(
            {
                "APP_ENV": "test",
                "ADMIN_ALLOW_DEV_AUTH": "true",
                "SERVICE_KEY": "openapi-check-service-key-0123456789abcdef",
                "SECRET_KEY": "openapi-check-secret-key-0123456789abcdef",
            }
        )
    code = "import json; from src.main import app; print(json.dumps(app.openapi()['paths']))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def contract_operations(contract: dict[str, object]) -> dict[str, dict[str, dict[str, object]]]:
    paths = contract.get("paths", {})
    return {
        str(path): {
            str(method).lower(): operation
            for method, operation in definition.items()
            if str(method).lower() in METHODS and isinstance(operation, dict)
        }
        for path, definition in paths.items()
        if isinstance(definition, dict)
    }


def main() -> int:
    errors: list[str] = []
    for filename, service_root in TARGETS.items():
        contract = yaml.safe_load((CONTRACT_ROOT / filename).read_text(encoding="utf-8"))
        expected = contract_operations(contract)
        actual = live_paths(service_root)
        missing_paths = sorted(set(expected) - set(actual))
        missing_methods = sorted(
            f"{path} {method.upper()}"
            for path, methods in expected.items()
            for method in set(methods) - set(actual.get(path, {}))
        )
        operation_id_mismatches = sorted(
            f"{path} {method.upper()}"
            for path, methods in expected.items()
            for method, operation in methods.items()
            if method in actual.get(path, {})
            and operation.get("operationId") != actual[path][method].get("operationId")
        )
        security_mismatches = sorted(
            f"{path} {method.upper()}"
            for path, methods in expected.items()
            for method, operation in methods.items()
            if method in actual.get(path, {})
            and bool(operation.get("security")) != bool(actual[path][method].get("security"))
        )
        response_mismatches = sorted(
            f"{path} {method.upper()}"
            for path, methods in expected.items()
            for method, operation in methods.items()
            if method in actual.get(path, {})
            and {str(code) for code in operation.get("responses", {}) if str(code).startswith("2")}
            > {str(code) for code in actual[path][method].get("responses", {}) if str(code).startswith("2")}
        )
        if missing_paths:
            errors.append(f"{filename}: missing live paths: {', '.join(missing_paths)}")
        if missing_methods:
            errors.append(f"{filename}: missing live methods: {', '.join(missing_methods)}")
        if operation_id_mismatches:
            errors.append(f"{filename}: operationId drift: {', '.join(operation_id_mismatches)}")
        if security_mismatches:
            errors.append(f"{filename}: security mismatch: {', '.join(security_mismatches)}")
        if response_mismatches:
            errors.append(f"{filename}: response status drift: {', '.join(response_mismatches)}")
        if not any((missing_paths, missing_methods, operation_id_mismatches, security_mismatches, response_mismatches)):
            print(f"PASS current OpenAPI target {filename}: {sum(len(methods) for methods in expected.values())} operations")

    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
