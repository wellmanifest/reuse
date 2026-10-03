#!/usr/bin/env python3
"""
Task generator for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Analyzes target repositories for reuse and deduplication opportunities,
and generates structured, actionable tickets for .planfile/sprints/current.yaml.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml


def run_redup_scan(project_path: Path) -> Dict[str, Any]:
    """Run redup scan on the project and return summary metrics."""
    try:
        cmd = [sys.executable, "-m", "redup", "scan", str(project_path)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines_scanned = 0
        dup_groups = 0
        for line in res.stdout.splitlines():
            if "files_scanned:" in line:
                try:
                    lines_scanned = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif "dup_groups:" in line:
                try:
                    dup_groups = int(line.split(":")[1].strip())
                except ValueError:
                    pass
        return {
            "success": res.returncode == 0,
            "dup_groups": dup_groups,
            "raw_output": res.stdout[:500]
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "dup_groups": 0}


def search_workspace_candidates(query: str) -> List[Dict[str, str]]:
    """Query subactor-search for candidate projects."""
    search_py = Path("/home/tom/github/semcod/search/src")
    if not search_py.exists():
        return []
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(search_py)
        cmd = [sys.executable, "-m", "subactor_search", "ask", query, "--json"]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            candidates = []
            for hit in data.get("hits", [])[:5]:
                proj = hit.get("project") or hit.get("repo") or "unknown"
                candidates.append({"project": proj, "file": hit.get("path", "")})
            return candidates
    except Exception:
        pass
    return []


def create_reuse_tasks(project_path: Path, topic: str = "") -> List[Dict[str, Any]]:
    """Generate planfile tasks based on reuse policy."""
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ts = int(time.time())
    proj_name = project_path.name

    tasks = [
        {
            "id": f"reuse_{ts}_1",
            "title": f"[{proj_name}] reuse(discovery): Identify existing {topic or proj_name} utilities in ~/github/*",
            "description": (
                f"## Context\n"
                f"Under Wellmanifest Reuse (`wellmanifest/reuse@v1` rule `REUSE-001` - Search Before Generate):\n"
                f"Before implementing new helper logic in `{proj_name}`, query local workspace index.\n\n"
                f"## Problem & Action\n"
                f"- Run `subactor-search ask '{topic or proj_name}'` to locate similar packages.\n"
                f"- Review found candidates (e.g. in `wellmanifest/*` or `semcod/*`) to consume shared interfaces.\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] AC-01: Candidate review recorded in docs/.\n"
                f"- [ ] AC-02: Zero redundant utility implementations introduced.\n\n"
                f"## Verification\n"
                f"```sh\n"
                f"git status --porcelain && pytest -q || npm test\n"
                f"```\n\n"
                f"## Planfile & Koru Autonomous Handoff\n"
                f"- Driven by: `koru autonomous`\n"
                f"- Mark done via: `planfile ticket done reuse_{ts}_1`\n"
            ),
            "priority": "high",
            "status": "todo",
            "tier": "reuse",
            "labels": ["reuse", "discovery", "koru-autonomous", "tier:reuse"],
            "satisfied_when": f"Workspace candidates identified and evaluated for {proj_name}.",
            "created_at": now_str,
            "source": "wellmanifest/reuse"
        },
        {
            "id": f"reuse_{ts}_2",
            "title": f"[{proj_name}] refactor(redup): Eliminate internal duplicate code and AST clones",
            "description": (
                f"## Context\n"
                f"Under Wellmanifest Reuse (`wellmanifest/reuse@v1` rule `REUSE-002` - Duplication & Clone Detection):\n"
                f"Run `redup scan` on `{proj_name}` and modularize duplicate blocks.\n\n"
                f"## Problem & Action\n"
                f"- Execute `python3 -m redup scan .` to identify clone clusters.\n"
                f"- Extract duplicated functions or scripts into reusable modules.\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] AC-01: No unmitigated duplicate groups with >= 30 lines.\n"
                f"- [ ] AC-02: All unit and integration tests pass with exit code 0.\n\n"
                f"## Verification\n"
                f"```sh\n"
                f"python3 -m redup check --threshold 0.85\n"
                f"```\n\n"
                f"## Planfile & Koru Autonomous Handoff\n"
                f"- Driven by: `koru autonomous`\n"
                f"- Mark done via: `planfile ticket done reuse_{ts}_2`\n"
            ),
            "priority": "medium",
            "status": "todo",
            "tier": "refactor",
            "labels": ["redup", "refactor", "koru-autonomous", "tier:refactor"],
            "satisfied_when": "redup scan reports zero unmitigated duplicate groups.",
            "created_at": now_str,
            "source": "wellmanifest/reuse"
        },
        {
            "id": f"reuse_{ts}_3",
            "title": f"[{proj_name}] docs(wellmanifest-docs): Enforce Compact v2 documentation and runbooks",
            "description": (
                f"## Context\n"
                f"Under Wellmanifest Reuse (`wellmanifest/reuse@v1` rule `REUSE-006` - Enforced Documentation Standards):\n"
                f"All user-authored repositories must conform to `wellmanifest/docs` and `wellmanifest/logs`.\n\n"
                f"## Problem & Action\n"
                f"- Ensure docs/ contains Compact v2 specifications (<= 120 lines / 600 words per feature).\n"
                f"- Ensure error runbooks or troubleshooting guide are present.\n"
                f"- Sync API reference using `semcod/code2docs` or `todocs` if applicable.\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] AC-01: Compact documentation present in docs/.\n"
                f"- [ ] AC-02: Troubleshooting and error handling runbook verified.\n\n"
                f"## Verification\n"
                f"```sh\n"
                f"test -f docs/ARCHITECTURE.md || test -d docs/FEATURE\n"
                f"```\n\n"
                f"## Planfile & Koru Autonomous Handoff\n"
                f"- Driven by: `koru autonomous`\n"
                f"- Mark done via: `planfile ticket done reuse_{ts}_3`\n"
            ),
            "priority": "medium",
            "status": "todo",
            "tier": "hygiene",
            "labels": ["docs", "wellmanifest-docs", "koru-autonomous", "tier:hygiene"],
            "satisfied_when": "Documentation conforms to wellmanifest/docs Compact v2 standard.",
            "created_at": now_str,
            "source": "wellmanifest/reuse"
        }
    ]

    return tasks


def update_planfile_sprint(sprint_path: Path, new_tasks: List[Dict[str, Any]], dry_run: bool = False) -> int:
    """Safely append or merge new reuse tasks into sprint file."""
    sprint_data: Dict[str, Any] = {"schema": "planfile.sprint/v1", "sprint": "current", "tasks": []}
    
    if sprint_path.exists():
        try:
            with open(sprint_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    sprint_data = loaded
        except Exception as exc:
            print(f"Warning: could not parse existing sprint file: {exc}", file=sys.stderr)

    existing_tasks = sprint_data.get("tasks", [])
    existing_titles = {t.get("title") for t in existing_tasks if isinstance(t, dict)}
    
    added_count = 0
    for task in new_tasks:
        if task["title"] not in existing_titles:
            existing_tasks.append(task)
            added_count += 1

    sprint_data["tasks"] = existing_tasks

    if dry_run:
        print(f"[DRY-RUN] Would append {added_count} reuse tasks to {sprint_path}:")
        for t in new_tasks:
            print(f"  ➜ {t['id']}: {t['title']}")
        return added_count

    sprint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sprint_path, "w", encoding="utf-8") as f:
        yaml.dump(sprint_data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    print(f"✅ Successfully written {added_count} reuse tasks to {sprint_path}")
    return added_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate planfile reuse & modularization tasks")
    parser.add_argument("--project", "-p", type=Path, default=Path.cwd(), help="Target project root")
    parser.add_argument("--topic", "-t", type=str, default="", help="Topic/domain keyword for search")
    parser.add_argument("--dry-run", action="store_true", help="Print tasks without modifying planfile")
    args = parser.parse_args()

    project_dir = args.project.resolve()
    if not project_dir.is_dir():
        print(f"Error: target project '{project_dir}' is not a directory.", file=sys.stderr)
        return 1

    print(f"🔍 Analyzing project for reuse: {project_dir.name}")
    tasks = create_reuse_tasks(project_dir, topic=args.topic)

    sprint_path = project_dir / ".planfile" / "sprints" / "current.yaml"
    added = update_planfile_sprint(sprint_path, tasks, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
