"""Compare normative OpenAPI paths with the live FastAPI applications."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "docs/NEOMARKET_PRODUCTION_SPEC_V2_2026-10-14/contracts"
LEGACY_INVENTORY = CONTRACT_ROOT / "legacy-routes.yaml"
SERVICES = {
    "http-b2c.openapi.yaml": "services/b2c",
    "http-b2b.openapi.yaml": "services/b2b",
    "http-admin.openapi.yaml": "services/admin",
}


def live_paths(service_root: str) -> dict[str, dict[str, dict[str, object]]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{service_root}{os.pathsep}shared"
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


def main() -> int:
    errors: list[str] = []
    inventory = yaml.safe_load(LEGACY_INVENTORY.read_text(encoding="utf-8"))
    if inventory.get("policy") != "transitional":
        errors.append("legacy-routes.yaml: policy must be transitional")
    legacy_inventory = {
        service: set()
        for service, entries in inventory.get("routes", {}).items()
    }
    for service, entries in inventory.get("routes", {}).items():
        for entry in entries:
            route = (str(entry.get("path", "")), str(entry.get("method", "")).lower())
            if not route[0] or route[1] not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                errors.append(f"legacy-routes.yaml: invalid route in {service}: {entry!r}")
                continue
            if not entry.get("owner"):
                errors.append(f"legacy-routes.yaml: missing owner for {service} {route[1].upper()} {route[0]}")
            sunset = entry.get("sunset")
            try:
                sunset_date = date.fromisoformat(str(sunset))
            except (TypeError, ValueError):
                errors.append(f"legacy-routes.yaml: invalid sunset for {service} {route[1].upper()} {route[0]}")
            else:
                if sunset_date < date.today():
                    errors.append(f"legacy-routes.yaml: expired sunset for {service} {route[1].upper()} {route[0]}")
            if route in legacy_inventory[service]:
                errors.append(f"legacy-routes.yaml: duplicate route for {service} {route[1].upper()} {route[0]}")
            legacy_inventory[service].add(route)
    for filename, service_root in SERVICES.items():
        service_name = filename.removeprefix("http-").removesuffix(".openapi.yaml")
        contract = yaml.safe_load((CONTRACT_ROOT / filename).read_text(encoding="utf-8"))
        expected = {
            path: {
                method.lower(): operation
                for method, operation in definition.items()
                if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}
            }
            for path, definition in contract.get("paths", {}).items()
        }
        actual = live_paths(service_root)
        missing_paths = sorted(set(expected) - set(actual))
        missing_methods = sorted(
            f"{path} {method.upper()}"
            for path, methods in expected.items()
            for method in set(methods) - set(actual.get(path, {}))
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
            and {
                code for code in operation.get("responses", {}) if str(code).startswith("2")
            }
            != {
                code
                for code in actual[path][method].get("responses", {})
                if str(code).startswith("2")
            }
        )
        undocumented_methods = sorted(
            f"{path} {method.upper()}"
            for path, methods in actual.items()
            if path.startswith(("/api/v1/", "/admin/v1/", "/internal/v1/"))
            for method in set(methods) - set(expected.get(path, {}))
        )
        undeclared_legacy = [
            route
            for route in undocumented_methods
            if (route.rsplit(" ", 1)[0], route.rsplit(" ", 1)[1].lower())
            not in legacy_inventory.get(service_name, set())
        ]
        if missing_paths or missing_methods:
            if missing_paths:
                errors.append(f"{filename}: missing live paths: {', '.join(missing_paths)}")
            if missing_methods:
                errors.append(f"{filename}: missing live methods: {', '.join(missing_methods)}")
            if security_mismatches:
                errors.append(f"{filename}: security mismatch: {', '.join(security_mismatches)}")
            if response_mismatches:
                errors.append(f"{filename}: response status drift: {', '.join(response_mismatches)}")
        else:
            print(f"PASS live OpenAPI routes {filename}: {len(expected)} contract paths")
            if security_mismatches:
                errors.append(f"{filename}: security mismatch: {', '.join(security_mismatches)}")
            if response_mismatches:
                errors.append(f"{filename}: response status drift: {', '.join(response_mismatches)}")
            if undeclared_legacy:
                errors.append(
                    f"{filename}: untracked legacy live routes: {', '.join(undeclared_legacy)}"
                )
            elif undocumented_methods:
                print(f"INFO tracked legacy routes: {len(undocumented_methods)}")
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
