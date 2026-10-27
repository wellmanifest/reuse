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


class RedupUnavailable(RuntimeError):
    """semcod/redup could not analyse the project; no receipt may be written."""


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
) -> tuple[str, list[dict[str, str]], list[frozenset[str]]]:
    """
    Run redup scan on target project.
    Returns (tool_version, scanned_file_entries, files_of_each_clone_group).
    """
    try:
        import contextlib
        import io
        try:
            import redup
        except ModuleNotFoundError:
            candidate_src = ROOT_DIR.parent.parent / "semcod" / "redup" / "src"
            if candidate_src.is_dir() and str(candidate_src) not in sys.path:
                sys.path.insert(0, str(candidate_src))
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

        groups = [
            frozenset(Path(fragment.file).as_posix() for fragment in group.fragments)
            for group in getattr(dup_map, "groups", [])
        ]
        return version, scanned, groups
    except Exception as exc:  # noqa: BLE001 - any analyzer failure means no evidence
        # Without a redup analysis there is no REUSE-002 evidence; a receipt
        # claiming zero clones would be a false "verified".
        raise RedupUnavailable(f"redup scan did not run: {exc}") from exc


SSOT_DECISION_SCHEMA = "wellmanifest.ssot/decision/v1"
# wellmanifest/ssot kinds that say the copies are intentionally not debt.
SSOT_NOT_DEBT_KINDS = frozenset({"allowed_divergence", "generated_mirror"})


def ssot_not_debt_trees(target: Path) -> list[tuple[str, frozenset[str]]]:
    """File sets that a wellmanifest/ssot decision classifies as not debt.

    Reads ``docs/ssot/*.ssot.json``. A tree reference ``path:symbol`` counts as
    its file. Unreadable or foreign documents are ignored, never trusted.
    """
    found: list[tuple[str, frozenset[str]]] = []
    for path in sorted((target / "docs" / "ssot").glob("*.ssot.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(document, dict) or document.get("schema") != SSOT_DECISION_SCHEMA:
            continue
        for decision in document.get("decisions") or []:
            if not isinstance(decision, dict) or decision.get("kind") not in SSOT_NOT_DEBT_KINDS:
                continue
            trees = frozenset(
                str(tree).split(":", 1)[0] for tree in decision.get("trees") or [] if isinstance(tree, str)
            )
            if trees:
                ref = f"{path.relative_to(target).as_posix()}#{decision.get('id', '')}"
                found.append((ref, trees))
    return found


def generate_receipt_data(
    target: Path,
    min_lines: int = 10,
    min_sim: float = 0.80,
    force_mitigated: bool = False,
) -> dict[str, Any]:
    """Generate in-memory receipt dictionary."""
    rev = get_git_head(target)
    tool_ver, scanned, groups = scan_with_redup(target, min_lines=min_lines, min_sim=min_sim)
    clone_groups = len(groups)

    # REUSE-002: every clone group needs an active plan, an explicit
    # mitigation, or a wellmanifest/ssot decision that it is not debt.
    decisions = ssot_not_debt_trees(target)
    ssot_mitigation = []
    for index, files in enumerate(groups):
        ref = next((ref for ref, trees in decisions if files and files <= trees), None)
        if ref:
            ssot_mitigation.append({"group": index, "decision": ref})
    has_plan = check_mitigation_in_planfile(target)
    unmitigated = 0 if (has_plan or force_mitigated) else clone_groups - len(ssot_mitigation)

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
            "ssot_mitigated": ssot_mitigation,
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
