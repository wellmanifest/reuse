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


def create_reuse_plan_data(project_path: Path, topic: str = "") -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate both planfile tasks list and canonical sprint tickets dict."""
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

    canonical_tickets: Dict[str, Any] = {}
    for t in tasks:
        tid = f"REUSE-{t['id'].upper()}"
        script_cmd = "git status --porcelain"
        if "redup" in t["labels"]:
            script_cmd = "python3 -m redup scan ."
        elif "docs" in t["labels"]:
            script_cmd = "test -f docs/ARCHITECTURE.md || test -d docs/FEATURE"
        elif "discovery" in t["labels"]:
            script_cmd = "PYTHONPATH=/home/tom/github/semcod/search/src python3 -m subactor_search ask 'tauri' --json || true"

        canonical_tickets[tid] = {
            "id": tid,
            "name": t["title"],
            "description": t["description"],
            "priority": "normal" if t["priority"] == "medium" else "high",
            "sprint": "current",
            "status": "open",
            "labels": t["labels"],
            "inputs": {
                "script": script_cmd,
                "expect_files_changed": False
            },
            "execution": {
                "attempt": 0,
                "max_attempts": 3,
                "queue": "default",
                "state": "ready"
            },
            "executor": {
                "kind": "shell",
                "mode": "autonomous"
            }
        }

    return tasks, canonical_tickets


def update_planfile_sprint(sprint_path: Path, new_tasks: List[Dict[str, Any]], canonical_tickets: Dict[str, Any], dry_run: bool = False) -> int:
    """Safely append or merge new reuse tasks into sprint file in canonical planfile format."""
    sprint_data: Dict[str, Any] = {
        "schema": "planfile.sprint/v1",
        "sprint": {
            "id": "current",
            "name": "Current Sprint",
            "status": "active",
            "tickets": {}
        },
        "tasks": []
    }
    
    if sprint_path.exists():
        try:
            with open(sprint_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    sprint_data = loaded
        except Exception as exc:
            print(f"Warning: could not parse existing sprint file: {exc}", file=sys.stderr)

    # Normalize sprint structure
    if not isinstance(sprint_data.get("sprint"), dict):
        sprint_data["sprint"] = {
            "id": "current",
            "name": "Current Sprint",
            "status": "active",
            "tickets": {}
        }
    elif "tickets" not in sprint_data["sprint"] or not isinstance(sprint_data["sprint"]["tickets"], dict):
        sprint_data["sprint"]["tickets"] = {}

    existing_tickets = sprint_data["sprint"]["tickets"]
    for tid, tdata in canonical_tickets.items():
        if tid not in existing_tickets:
            existing_tickets[tid] = tdata

    existing_tasks = sprint_data.get("tasks", [])
    if not isinstance(existing_tasks, list):
        existing_tasks = []
    existing_titles = {t.get("title") for t in existing_tasks if isinstance(t, dict)}
    
    added_count = 0
    for task in new_tasks:
        if task["title"] not in existing_titles:
            existing_tasks.append(task)
            added_count += 1

    sprint_data["tasks"] = existing_tasks

    if dry_run:
        print(f"[DRY-RUN] Would append {added_count} reuse tasks to {sprint_path}")
        return added_count

    sprint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sprint_path, "w", encoding="utf-8") as f:
        yaml.dump(sprint_data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    print(f"✅ Successfully written {len(canonical_tickets)} canonical tickets to {sprint_path}")
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
    tasks, tickets = create_reuse_plan_data(project_dir, topic=args.topic)

    sprint_path = project_dir / ".planfile" / "sprints" / "current.yaml"
    added = update_planfile_sprint(sprint_path, tasks, tickets, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
