"""Validate the shape of the current NeoMarket Admin specification.

This is a structural CI check. Runtime acceptance remains the responsibility
of the acceptance matrix and release checker; this script only prevents CI
from silently validating a deleted/obsolete specification.
"""

from __future__ import annotations

import csv
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = ROOT / "docs/NeoMarket_Admin_Production_Spec_2026-10-16"
REQUIRED_FILES = (
    "COMPLETE_SPEC.md",
    "MASTER_SPEC.md",
    "contracts/admin-target.openapi.yaml",
    "contracts/b2b-admin-internal-target.openapi.yaml",
    "qa/ACCEPTANCE_MATRIX.csv",
    "qa/check_release.py",
    "qa/RELEASE_GATES.md",
    "qa/TRACEABILITY.md",
)
MATRIX_COLUMNS = {
    "test_id",
    "requirement_id",
    "priority",
    "scenario",
    "test_layer",
    "expected_result",
    "status",
    "evidence_path",
    "owner",
}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
ALLOWED_STATUSES = {"PASS", "NOT_RUN", "BLOCKED", "PARTIAL", "FAIL"}
OPENAPI_FILES = (
    "contracts/admin-target.openapi.yaml",
    "contracts/b2b-admin-internal-target.openapi.yaml",
)


def validate_openapi(relative_path: str, errors: list[str]) -> None:
    path = SPEC_ROOT / relative_path
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{relative_path}: cannot parse YAML ({exc})")
        return
    if not isinstance(document, dict):
        errors.append(f"{relative_path}: root must be a mapping")
        return
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        errors.append(f"{relative_path}: openapi must be a 3.x version")
    if not isinstance(document.get("info"), dict):
        errors.append(f"{relative_path}: info must be a mapping")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append(f"{relative_path}: paths must be a non-empty mapping")
        return
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    for route, definition in paths.items():
        if not isinstance(route, str) or not route.startswith("/"):
            errors.append(f"{relative_path}: invalid route {route!r}")
            continue
        if not isinstance(definition, dict):
            errors.append(f"{relative_path}: {route}: definition must be a mapping")
            continue
        for method, operation in definition.items():
            if method.lower() not in methods:
                continue
            if not isinstance(operation, dict):
                errors.append(f"{relative_path}: {route} {method}: operation must be a mapping")
                continue
            if not operation.get("operationId"):
                errors.append(f"{relative_path}: {route} {method}: missing operationId")
            if not isinstance(operation.get("responses"), dict) or not operation["responses"]:
                errors.append(f"{relative_path}: {route} {method}: missing responses")


def validate_matrix(errors: list[str]) -> int:
    relative_path = "qa/ACCEPTANCE_MATRIX.csv"
    path = SPEC_ROOT / relative_path
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = set(reader.fieldnames or ())
            if columns != MATRIX_COLUMNS:
                errors.append(
                    f"{relative_path}: columns differ from required schema: "
                    f"missing={sorted(MATRIX_COLUMNS - columns)}, extra={sorted(columns - MATRIX_COLUMNS)}"
                )
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        errors.append(f"{relative_path}: cannot parse CSV ({exc})")
        return 0

    if not rows:
        errors.append(f"{relative_path}: matrix must contain at least one test")
        return 0
    test_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        for column in MATRIX_COLUMNS - {"evidence_path", "owner"}:
            if not row.get(column, "").strip():
                errors.append(f"{relative_path}:{row_number}: empty {column}")
        test_id = row.get("test_id", "").strip()
        if test_id in test_ids:
            errors.append(f"{relative_path}:{row_number}: duplicate test_id {test_id}")
        test_ids.add(test_id)
        priority = row.get("priority", "").strip()
        if priority not in ALLOWED_PRIORITIES:
            errors.append(f"{relative_path}:{row_number}: invalid priority {priority!r}")
        status = row.get("status", "").strip()
        if status not in ALLOWED_STATUSES:
            errors.append(f"{relative_path}:{row_number}: invalid status {status!r}")
        if status == "PASS" and not row.get("evidence_path", "").strip():
            errors.append(f"{relative_path}:{row_number}: PASS requires evidence_path")
    return len(rows)


def main() -> int:
    errors: list[str] = []
    missing = [relative for relative in REQUIRED_FILES if not (SPEC_ROOT / relative).is_file()]
    errors.extend(f"missing current spec file: {relative}" for relative in missing)
    if not missing:
        for relative in OPENAPI_FILES:
            validate_openapi(relative, errors)
        row_count = validate_matrix(errors)
    else:
        row_count = 0
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1
    print(f"PASS current NeoMarket Admin spec: {len(OPENAPI_FILES)} OpenAPI contracts, {row_count} acceptance cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
