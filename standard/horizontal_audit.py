"""Static AST Horizontal Complexity Profiler (REUSE-015)."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SKIP_DIRS = {
    ".git", ".governance", ".koru", ".mypy_cache", ".planfile", ".pytest_cache",
    ".ruff_cache", ".subactor", ".venv", ".worktrees", "__pycache__", "_bundled",
    "build", "dist", "node_modules", "target", "venv",
}
_STDLIB_NAMES: frozenset[str] = getattr(sys, "stdlib_module_names", frozenset()) | {"__future__", "typing_extensions"}


def _if_chain_length(node: ast.If) -> int:
    arms = 1
    cur: Optional[ast.If] = node
    while cur is not None and len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
        arms += 1
        cur = cur.orelse[0]
    if cur is not None and cur.orelse:
        arms += 1
    return arms


def analyze_horizontal_complexity(
    project_root: Path,
    *,
    max_branch_arms: int = 5,
    max_fan_out: int = 12,
    max_file_lines: int = 500,
    include_tests: bool = False,
) -> Dict[str, Any]:
    """Scan Python modules for horizontal complexity hotspots (REUSE-015)."""
    root = project_root.resolve()
    hotspots: List[Dict[str, Any]] = []
    scanned_files = 0
    skip_dirs = set(_SKIP_DIRS)
    if not include_tests:
        skip_dirs.update({"test", "tests", "examples"})

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs and not d.startswith("."))
        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            if fpath.is_symlink():
                continue
            rel = fpath.relative_to(root).as_posix()
            try:
                source = fpath.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=rel)
            except (OSError, UnicodeError, SyntaxError):
                continue
            scanned_files += 1
            lines_count = len(source.splitlines())
            if lines_count > max_file_lines:
                hotspots.append({
                    "code": "REUSE-015-MONOLITH",
                    "path": rel,
                    "line": 1,
                    "metric": lines_count,
                    "limit": max_file_lines,
                    "remediation": "Split module into focused stages/facades (REUSE-011, REUSE-018).",
                })

            peer_imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in _STDLIB_NAMES:
                            peer_imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    if node.level > 0 or top not in _STDLIB_NAMES:
                        peer_imports.add(node.module)
            if len(peer_imports) > max_fan_out:
                hotspots.append({
                    "code": "REUSE-015-FANOUT",
                    "path": rel,
                    "line": 1,
                    "metric": len(peer_imports),
                    "limit": max_fan_out,
                    "remediation": "Reduce horizontal peer imports using DependencyResolver or StreamPipeline (REUSE-017, REUSE-018).",
                })

            visited_ifs: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and id(node) not in visited_ifs:
                    cur: Optional[ast.If] = node
                    while cur is not None:
                        visited_ifs.add(id(cur))
                        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                            cur = cur.orelse[0]
                        else:
                            cur = None
                    arms = _if_chain_length(node)
                    if arms >= max_branch_arms:
                        hotspots.append({
                            "code": "REUSE-015-BRANCH-CHAIN",
                            "path": rel,
                            "line": getattr(node, "lineno", 1),
                            "metric": arms,
                            "limit": max_branch_arms - 1,
                            "remediation": "Replace wide if/elif chain with declarative DecisionEngine or CommandSpec table (REUSE-012, REUSE-016).",
                        })

    return {
        "schema": "wellmanifest.horizontal-complexity-report/v1",
        "project": str(root),
        "scanned_files": scanned_files,
        "hotspot_count": len(hotspots),
        "hotspots": hotspots,
    }
