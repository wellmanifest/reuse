#!/usr/bin/env python3
"""
Conformance checker for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Validates repository compliance with reuse rules (REUSE-001..006).
"""

from __future__ import annotations

import argparse
import json
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


def check_schema_files(root: Path) -> bool:
    """Validate that standard policy and tool bindings are valid JSON."""
    policy_path = root / "standard" / "reuse-policy.json"
    bindings_path = root / "standard" / "tool-bindings.json"
    
    if not policy_path.exists() or not bindings_path.exists():
        return False
    
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            policy = json.load(f)
            if not isinstance(policy, dict) or policy.get("schema") != "wellmanifest.reuse-policy/v1":
                raise ValueError("invalid policy identity")
            rules = policy.get("rules")
            if not isinstance(rules, list) or len(rules) < 6 or any(not isinstance(rule, dict) for rule in rules):
                raise ValueError("invalid policy rules")
            
        with open(bindings_path, "r", encoding="utf-8") as f:
            bindings = json.load(f)
            if not isinstance(bindings, dict) or bindings.get("schema") != "wellmanifest.reuse-tool-bindings/v1":
                raise ValueError("invalid bindings identity")
            entries = bindings.get("bindings")
            if not isinstance(entries, list) or len(entries) < 8 or any(not isinstance(entry, dict) for entry in entries):
                raise ValueError("invalid tool bindings")
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

    # No trusted scan adapter is bound yet. Eligibility and file presence cannot
    # establish that duplication was measured or that findings were mitigated.
    result.add_check(
        "REUSE-002", "Duplication & Clone Awareness", False,
        "Unverified: no validated, revision-bound redup scan evidence adapter",
        {"path": str(target_dir), "status": "unverified"},
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
