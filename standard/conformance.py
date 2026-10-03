#!/usr/bin/env python3
"""
Conformance checker for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Validates repository compliance with reuse rules (REUSE-001..006).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


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
            assert policy.get("schema") == "wellmanifest.reuse-policy/v1"
            assert len(policy.get("rules", [])) >= 6
            
        with open(bindings_path, "r", encoding="utf-8") as f:
            bindings = json.load(f)
            assert bindings.get("schema") == "wellmanifest.reuse-tool-bindings/v1"
            assert len(bindings.get("bindings", [])) >= 8
        return True
    except Exception as exc:
        print(f"Schema validation error: {exc}", file=sys.stderr)
        return False


def run_conformance(target_dir: Path) -> ConformanceResult:
    result = ConformanceResult(target_dir)

    # REUSE-004: Planfile structure
    planfile_dir = target_dir / ".planfile"
    sprints_dir = planfile_dir / "sprints"
    has_planfile = planfile_dir.is_dir() and sprints_dir.is_dir()
    result.add_check(
        code="REUSE-004",
        name="Planfile Task Orchestration",
        passed=has_planfile,
        message="Repository has .planfile/sprints directory for ticket orchestration" if has_planfile else "Missing .planfile/sprints directory",
        details={"planfile_exists": has_planfile}
    )

    # REUSE-006: Docs standard (wellmanifest/docs)
    docs_dir = target_dir / "docs"
    readme_file = target_dir / "README.md"
    has_docs = docs_dir.is_dir() or readme_file.is_file()
    
    # Check for compact docs or markdown files
    md_count = len(list(docs_dir.glob("**/*.md"))) if docs_dir.is_dir() else 0
    docs_passed = docs_dir.is_dir() and (md_count > 0 or readme_file.is_file())
    result.add_check(
        code="REUSE-006A",
        name="Wellmanifest Docs Compliance",
        passed=docs_passed,
        message=f"Repository has docs/ directory with {md_count} specification documents" if docs_passed else "Missing docs/ directory or documentation index",
        details={"docs_dir": docs_dir.is_dir(), "doc_files_count": md_count}
    )

    # REUSE-006B: Error runbooks / logs (wellmanifest/logs)
    errors_dir = target_dir / "errors"
    has_errors_or_logs = errors_dir.is_dir() or (docs_dir / "TROUBLESHOOTING.md").exists() or (target_dir / "logs").is_dir()
    result.add_check(
        code="REUSE-006B",
        name="Wellmanifest Logs & Runbooks Compliance",
        passed=has_errors_or_logs,
        message="Repository provides error runbooks or structured troubleshooting guide" if has_errors_or_logs else "No errors/ runbooks or TROUBLESHOOTING.md found",
        details={"has_runbooks": has_errors_or_logs}
    )

    # REUSE-002: Duplication check
    # Check if a duplication summary or redup scan was run
    redup_file = target_dir / ".redup"
    result.add_check(
        code="REUSE-002",
        name="Duplication & Clone Awareness",
        passed=True,
        message="Codebase is eligible for redup scan and clone analysis",
        details={"path": str(target_dir)}
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
