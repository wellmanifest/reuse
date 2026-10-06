#!/usr/bin/env python3
"""
Conformance checker for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Validates repository compliance with reuse rules (REUSE-001..006).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml


class ConformanceResult:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self.passed: bool = True
        self.checks: List[Dict[str, Any]] = []

    def add_check(self, code: str, name: str, passed: bool, message: str, details: Any = None):
        if not passed:
            self.passed = False
        self.checks.append({
            "code": code,
            "name": name,
            "passed": passed,
            "message": message,
            "details": details or {}
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wellmanifest.reuse-conformance/v1",
            "target": str(self.target_dir),
            "passed": self.passed,
            "checks": self.checks,
            "total_checks": len(self.checks),
            "failed_checks": sum(1 for c in self.checks if not c["passed"])
        }


def _unique(values: List[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def check_schema_files(root: Path) -> bool:
    """Validate policy and tool bindings against JSON Schemas.

    Uses explicit exceptions (never ``assert``) so rejection is identical under ``python -O``.
    """
    from jsonschema import Draft202012Validator

    policy_path = root / "standard" / "reuse-policy.json"
    bindings_path = root / "standard" / "tool-bindings.json"
    pairs = (
        (policy_path, root / "schemas" / "reuse-policy.schema.json", "rules", "rule codes"),
        (bindings_path, root / "schemas" / "tool-bindings.schema.json", "bindings", "binding codes"),
    )
    try:
        for data_path, schema_path, key, label in pairs:
            data = json.loads(data_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
            if errors:
                first = errors[0]
                raise ValueError(f"{data_path.name}: {'/'.join(map(str, first.path)) or '<root>'}: {first.message}")
            _unique([entry["code"] for entry in data[key]], label)
        return True
    except Exception as exc:
        print(f"Schema validation error: {exc}", file=sys.stderr)
        return False


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def _has_sprint(sprints_dir: Path) -> bool:
    for path in sorted(sprints_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        sprint = data.get("sprint")
        if (isinstance(sprint, dict) and isinstance(sprint.get("id"), str)
                and sprint["id"].strip() and isinstance(sprint.get("tickets"), dict)):
            return True
    return False


RECEIPT_PATH = Path(".reuse") / "redup-receipt.json"
RECEIPT_SCHEMA = "wellmanifest.reuse-scan-receipt/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")


def _git(target: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True, timeout=30)


def evaluate_scan_receipt(target: Path) -> Dict[str, Any]:
    """Validate REUSE-002 scan evidence; any missing/stale/invalid input is not a pass.

    The receipt binds a scan to a git revision that must be an ancestor of HEAD and to
    the sha256 of every scanned file as it exists now, so edits after the scan make it
    stale. Producer authentication is NOT verified here (reported as such).
    """
    def verdict(status: str, reason: str, **extra: Any) -> Dict[str, Any]:
        return {"passed": status == "verified", "status": status, "reason": reason,
                "producer_authenticated": False, **extra}

    path = target / RECEIPT_PATH
    if not path.is_file():
        return verdict("unverified", "no scan receipt")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return verdict("invalid", "receipt is not readable JSON")
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return verdict("invalid", "wrong receipt schema")
    tool = receipt.get("tool")
    if not (isinstance(tool, dict) and all(isinstance(tool.get(k), str) and tool[k].strip() for k in ("name", "version"))):
        return verdict("invalid", "tool name/version required")
    revision = receipt.get("revision")
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        return verdict("invalid", "revision must be a 40-hex git commit")
    scanned = receipt.get("scanned")
    if not isinstance(scanned, list) or not scanned:
        return verdict("invalid", "scanned file digests required")
    findings = receipt.get("findings")
    if not (isinstance(findings, dict) and all(type(findings.get(k)) is int and findings[k] >= 0
                                               for k in ("clone_groups", "unmitigated"))):
        return verdict("invalid", "findings.clone_groups and findings.unmitigated must be non-negative integers")
    root = target.resolve()
    for entry in scanned:
        rel = entry.get("path") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(rel, str) or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            return verdict("invalid", "each scanned entry needs path and sha256")
        file = (root / rel).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            return verdict("stale", f"scanned file missing or outside project: {rel}")
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            return verdict("stale", f"scanned file changed after scan: {rel}")
    try:
        exists = _git(target, "cat-file", "-e", f"{revision}^{{commit}}").returncode == 0
        ancestor = exists and _git(target, "merge-base", "--is-ancestor", revision, "HEAD").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return verdict("unverified", "git revision could not be observed")
    if not ancestor:
        return verdict("stale", "receipt revision is not an ancestor of HEAD")
    if findings["unmitigated"] > 0:
        return verdict("failed", "unmitigated clone groups remain", findings=findings)
    return verdict("verified", "revision- and digest-bound scan with no unmitigated clones", findings=findings)


def run_conformance(target_dir: Path) -> ConformanceResult:
    """Check bounded content evidence; do not certify unobserved enforcement."""
    result = ConformanceResult(target_dir)
    has_planfile = _has_sprint(target_dir / ".planfile" / "sprints")
    result.add_check(
        "REUSE-004", "Planfile Task Orchestration", has_planfile,
        "Parsed sprint with ID and ticket mapping" if has_planfile else "No parseable sprint with ID and ticket mapping",
        {"planfile_exists": has_planfile, "standard_enforcement_verified": False},
    )

    docs_dir = target_dir / "docs"
    md_count = sum(_nonempty(path) for path in docs_dir.glob("**/*.md"))
    has_docs = _nonempty(docs_dir / "README.md")
    result.add_check(
        "REUSE-006A", "Documentation Index Evidence", has_docs,
        "Nonempty docs/README.md index present" if has_docs else "Missing nonempty docs/README.md index",
        {"docs_dir": docs_dir.is_dir(), "doc_files_count": md_count,
         "standard_enforcement_verified": False},
    )

    has_runbooks = any(_nonempty(path) for path in (target_dir / "errors").glob("*.md"))
    has_runbooks = has_runbooks or _nonempty(docs_dir / "TROUBLESHOOTING.md")
    result.add_check(
        "REUSE-006B", "Runbook Content Evidence", has_runbooks,
        "Nonempty runbook or troubleshooting guide present" if has_runbooks else "Missing nonempty runbook or troubleshooting guide",
        {"has_runbooks": has_runbooks, "standard_enforcement_verified": False},
    )

    scan = evaluate_scan_receipt(target_dir)
    result.add_check(
        "REUSE-002", "Duplication & Clone Awareness", scan["passed"],
        f"{scan['status'].capitalize()}: {scan['reason']}",
        {"path": str(target_dir), **scan},
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Wellmanifest Reuse Conformance Checker")
    parser.add_argument("--project", "-p", type=Path, default=Path.cwd(), help="Target project root directory")
    parser.add_argument("--check-schema", action="store_true", help="Validate standard policy and tool bindings schemas")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    args = parser.parse_args()

    standard_root = Path(__file__).resolve().parent.parent
    if args.check_schema:
        valid = check_schema_files(standard_root)
        if args.json:
            print(json.dumps({"schema_valid": valid, "standard_root": str(standard_root)}, indent=2))
        else:
            print(f"Standard schemas valid: {'YES' if valid else 'NO'}")
        return 0 if valid else 1

    res = run_conformance(args.project)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"\n📦 Wellmanifest Reuse Conformance Report: {args.project.name}")
        print(f"Overall Status: {'✅ PASSED' if res.passed else '❌ FAILED'}\n")
        for chk in res.checks:
            icon = "✅" if chk["passed"] else "⚠️"
            print(f"  {icon} [{chk['code']}] {chk['name']}: {chk['message']}")
        print()

    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
