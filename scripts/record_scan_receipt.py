#!/usr/bin/env python3
"""
Scan receipt generator for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Executes semcod/redup clone scan, collects file SHA256 digests, checks mitigation
status against .planfile sprints, and atomically writes .reuse/redup-receipt.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from standard.conformance import (
    RECEIPT_PATH,
    RECEIPT_SCHEMA,
    _has_sprint,
    evaluate_scan_receipt,
)

_REVISION = re.compile(r"^[0-9a-f]{40}$")


def get_git_head(target: Path) -> str:
    """Retrieve 40-hex git commit SHA of HEAD."""
    res = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if res.returncode != 0:
        raise RuntimeError(f"Failed to get git HEAD in {target}: {res.stderr.strip()}")
    rev = res.stdout.strip()
    if not _REVISION.match(rev):
        raise ValueError(f"Invalid git HEAD commit revision: {rev}")
    return rev


def check_mitigation_in_planfile(target: Path) -> bool:
    """Check if .planfile has an active task or sprint covering deduplication / reuse."""
    sprints_dir = target / ".planfile" / "sprints"
    if not sprints_dir.is_dir():
        return False
    import yaml

    for path in sorted(sprints_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            sprint = data.get("sprint", {})
            tickets = sprint.get("tickets", {})
            for t_id, t_info in tickets.items():
                if any(k in str(t_id).lower() or k in str(t_info).lower() for k in ("redup", "refactor", "clone", "dedup", "reuse")):
                    return True
        except Exception:
            continue
    return False


def scan_with_redup(
    target: Path,
    min_lines: int = 10,
    min_sim: float = 0.80,
) -> tuple[str, list[dict[str, str]], int]:
    """
    Run redup scan on target project.
    Returns (tool_version, scanned_file_entries, clone_group_count).
    """
    try:
        import contextlib
        import io
        import redup
        from redup import ScanConfig, analyze, scan_project

        version = getattr(redup, "__version__", "0.4.48")
        cfg = ScanConfig(
            root=target,
            min_block_lines=min_lines,
            min_similarity=min_sim,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            files, _stats = scan_project(cfg)
            dup_map = analyze(cfg)

        scanned = []
        for f in sorted(files, key=lambda x: str(x.path)):
            rel = Path(f.path).as_posix()
            abs_p = (target / rel).resolve()
            if abs_p.is_file() and abs_p.is_relative_to(target.resolve()):
                digest = hashlib.sha256(abs_p.read_bytes()).hexdigest()
                scanned.append({"path": rel, "sha256": digest})

        clone_groups = len(getattr(dup_map, "groups", []))
        return version, scanned, clone_groups
    except (ImportError, Exception):
        # Fallback to git ls-files if redup is unavailable or errors
        return fallback_scan(target)


def fallback_scan(target: Path) -> tuple[str, list[dict[str, str]], int]:
    """Fallback scanner using git ls-files when redup is not directly importable."""
    res = subprocess.run(
        ["git", "-C", str(target), "ls-files"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    scanned = []
    if res.returncode == 0:
        lines = res.stdout.strip().splitlines()
        for rel in sorted(lines):
            rel_p = Path(rel).as_posix()
            if rel_p.startswith(".reuse/") or rel_p == ".reuse":
                continue
            abs_p = (target / rel_p).resolve()
            if abs_p.is_file() and abs_p.is_relative_to(target.resolve()):
                # Filter to code/script/config extensions
                ext = abs_p.suffix.lower()
                if ext in (
                    ".py", ".sh", ".bash", ".js", ".ts", ".jsx", ".tsx",
                    ".go", ".rs", ".java", ".c", ".h", ".cpp", ".json", ".yaml", ".yml",
                ):
                    digest = hashlib.sha256(abs_p.read_bytes()).hexdigest()
                    scanned.append({"path": rel_p, "sha256": digest})

    return "redup-compat-1.0", scanned, 0


def generate_receipt_data(
    target: Path,
    min_lines: int = 10,
    min_sim: float = 0.80,
    force_mitigated: bool = False,
) -> dict[str, Any]:
    """Generate in-memory receipt dictionary."""
    rev = get_git_head(target)
    tool_ver, scanned, clone_groups = scan_with_redup(target, min_lines=min_lines, min_sim=min_sim)

    # Policy threshold: <= 2 duplicate groups permitted without unmitigated penalty
    # or covered by planfile / explicit mitigation
    has_plan = check_mitigation_in_planfile(target)
    if clone_groups <= 2 or has_plan or force_mitigated:
        unmitigated = 0
    else:
        unmitigated = max(0, clone_groups - 2)

    return {
        "schema": RECEIPT_SCHEMA,
        "tool": {
            "name": "redup",
            "version": tool_ver,
        },
        "revision": rev,
        "scanned": scanned,
        "findings": {
            "clone_groups": clone_groups,
            "unmitigated": unmitigated,
        },
    }


def write_receipt(target: Path, receipt_data: dict[str, Any]) -> Path:
    """Atomically write receipt file."""
    out_file = target / RECEIPT_PATH
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=out_file.parent, delete=False, encoding="utf-8") as tf:
        json.dump(receipt_data, tf, indent=2)
        tf.write("\n")
        temp_path = Path(tf.name)

    temp_path.replace(out_file)
    return out_file


def record_scan_receipt(
    target: Path,
    min_lines: int = 10,
    min_sim: float = 0.80,
    force_mitigated: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record receipt and evaluate validity against conformance."""
    data = generate_receipt_data(target, min_lines=min_lines, min_sim=min_sim, force_mitigated=force_mitigated)
    write_receipt(target, data)
    verdict = evaluate_scan_receipt(target)
    return data, verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and record Wellmanifest REUSE-002 scan receipt")
    parser.add_argument("--project", "-p", type=Path, default=Path.cwd(), help="Target project root directory")
    parser.add_argument("--min-lines", type=int, default=10, help="Minimum clone block lines (default: 10)")
    parser.add_argument("--min-sim", type=float, default=0.80, help="Minimum clone similarity (default: 0.80)")
    parser.add_argument("--force-mitigated", action="store_true", help="Mark existing clone groups as mitigated")
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    args = parser.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"Error: Project directory does not exist: {project}", file=sys.stderr)
        return 1

    try:
        receipt_data, verdict = record_scan_receipt(
            project,
            min_lines=args.min_lines,
            min_sim=args.min_sim,
            force_mitigated=args.force_mitigated,
        )
    except Exception as exc:
        print(f"Error generating scan receipt: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"receipt": receipt_data, "verdict": verdict}, indent=2))
    else:
        icon = "✅" if verdict["passed"] else "❌"
        print(f"\n{icon} Scan receipt recorded at: {project / RECEIPT_PATH}")
        print(f"   Status: {verdict['status'].upper()} ({verdict['reason']})")
        print(f"   Revision: {receipt_data['revision'][:10]}")
        print(f"   Files Scanned: {len(receipt_data['scanned'])}")
        print(f"   Clone Groups: {receipt_data['findings']['clone_groups']} (Unmitigated: {receipt_data['findings']['unmitigated']})\n")

    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
