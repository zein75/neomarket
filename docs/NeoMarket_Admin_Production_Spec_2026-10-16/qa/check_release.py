#!/usr/bin/env python3
"""Evidence gate for NeoMarket Admin. Only verifies supplied evidence manifest; cannot run tests.

Usage:
  python qa/check_release.py --matrix qa/ACCEPTANCE_MATRIX.csv --runs-dir qa-reports/admin/final

Manifest expected in each of three distinct directories: manifest.json
{
  "run_id": "uuid",
  "commit_sha": "40-char Git SHA",
  "environment": "isolated-staging",
  "executed_at": "2026-10-16T00:00:00Z",
  "cases": [{"test_id": "AT-001", "status": "PASS", "evidence": ["report.html"]}, ...],
  "critical_findings_open": 0,
  "flaky_tests": 0,
  "skipped_tests": 0
}
The manifest and checks are not tamper-proof. CI artifact integrity and review required.
"""

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r"^[0-9a-f]{40}$", re.I)
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "SKIPPED", "FLAKY"}


def check(matrix, run_dir):
    errors = []
    matrix_path = Path(matrix)
    with matrix_path.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    expected = {r["test_id"] for r in rows}
    if not expected or len(expected) != len(rows):
        errors.append("Invalid or duplicate matrix test IDs")
    valid_matrix_statuses = {"PASS", "NOT_RUN", "BLOCKED", "FAIL", "SKIPPED", "FLAKY"}
    for row in rows:
        status = row.get("status", "").strip()
        test_id = row.get("test_id", "<unknown>")
        if status not in valid_matrix_statuses:
            errors.append(f"{test_id}: invalid matrix status {status!r}")
        if status == "PASS":
            evidence = row.get("evidence_path", "").strip()
            if not evidence:
                errors.append(f"{test_id}: PASS has no evidence_path")
            else:
                evidence_path = Path(evidence)
                if (
                    evidence_path.is_absolute()
                    or ".." in evidence_path.parts
                    or not evidence_path.is_file()
                ):
                    errors.append(
                        f"{test_id}: PASS evidence_path is missing or unsafe: {evidence}"
                    )
    manifests = sorted(Path(run_dir).glob("*/manifest.json"))
    if len(manifests) != 3:
        errors.append(
            f"Exactly 3 independent manifests required, found {len(manifests)}"
        )
    run_ids = set()
    sha = None
    timestamps = set()
    for mf in manifests:
        try:
            payload = json.loads(mf.read_text(encoding="utf8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{mf}: unreadable manifest: {exc}")
            continue
        rid = payload.get("run_id")
        timestamp = payload.get("executed_at")
        commit = payload.get("commit_sha")
        if not rid or rid in run_ids:
            errors.append(f"{mf}: missing/duplicate run_id")
        run_ids.add(rid)
        if timestamp in timestamps:
            errors.append(f"{mf}: repeated execution timestamp")
        timestamps.add(timestamp)
        try:
            x = dt.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if x.tzinfo is None:
                raise ValueError("naive timestamp")
        except ValueError:
            errors.append(f"{mf}: invalid executed_at")
        if not isinstance(commit, str) or not SHA.fullmatch(commit):
            errors.append(f"{mf}: invalid commit SHA")
        if sha is not None and commit != sha:
            errors.append(f"{mf}: different commit SHA")
        sha = commit
        if payload.get("critical_findings_open") != 0:
            errors.append(f"{mf}: critical findings still open or unknown")
        if payload.get("flaky_tests") != 0 or payload.get("skipped_tests") != 0:
            errors.append(f"{mf}: flaky/skipped tests")
        cases = payload.get("cases", [])
        if not isinstance(cases, list):
            errors.append(f"{mf}: cases must be list")
            continue
        IDs = [c.get("test_id") for c in cases if isinstance(c, dict)]
        if len(IDs) != len(set(IDs)):
            errors.append(f"{mf}: duplicate test IDs")
        if set(IDs) != expected:
            errors.append(
                f"{mf}: missing={len(expected - set(IDs))}, unexpected={len(set(IDs) - expected)}"
            )
        for c in cases:
            if not isinstance(c, dict):
                errors.append(f"{mf}: malformed case")
                continue
            status = c.get("status")
            if status not in STATUSES:
                errors.append(f"{mf}: invalid status {status}")
                continue
            if status != "PASS":
                errors.append(f"{mf}: {c.get('test_id')}: {status}")
            proofs = c.get("evidence", [])
            if not isinstance(proofs, list) or not proofs:
                errors.append(f"{mf}: {c.get('test_id')}: no evidence")
                continue
            for proof in proofs:
                if (
                    not isinstance(proof, str)
                    or not proof
                    or Path(proof).is_absolute()
                    or ".." in Path(proof).parts
                    or not (mf.parent / proof).is_file()
                ):
                    errors.append(f"{mf}: invalid/missing evidence {proof}")
        if payload.get("environment") not in ("isolated-staging", "staging"):
            errors.append(f"{mf}: unsupported environment for release gate")
    return errors, len(expected)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", required=True)
    p.add_argument("--runs-dir", required=True)
    a = p.parse_args()
    errors, n = check(a.matrix, a.runs_dir)
    print(
        json.dumps(
            {
                "result": "BLOCKED" if errors else "PASS",
                "required_cases": n,
                "issues": errors[:30],
                "issue_count": len(errors),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
