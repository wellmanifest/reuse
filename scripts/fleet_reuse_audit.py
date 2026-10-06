#!/usr/bin/env python3
"""
Fleet-wide auditor and task orchestrator for Wellmanifest Reuse Standard (wellmanifest/reuse@v1).
Scans non-fork user/org repositories, verifies compliance with wellmanifest/docs & wellmanifest/logs,
runs deduplication audits (redup), and generates planfile tickets for autonomous Koru execution.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.generate_reuse_plan import create_reuse_plan_data, update_planfile_sprint
from standard.conformance import run_conformance


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or (path / ".git").is_file()


def is_fork(path: Path) -> bool:
    """Check git remote to verify if repository is an upstream third-party fork."""
    try:
        res = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5
        )
        url = res.stdout.strip()
        # Non-fork user organizations
        user_orgs = (
            "github.com:wellmanifest/",
            "github.com:semcod/",
            "github.com:paxlet-com/",
            "github.com:digitaltwin-run/",
            "github.com:maskservice/",
            "github.com:autogrammar/",
            "github.com:subactor/",
            "github.com:twinerd/",
            "github.com:clonerd-com/",
            "github.com:wronai/",
            "github.com:pactown-com/",
            "github.com/wellmanifest/",
            "github.com/semcod/",
            "github.com/paxlet-com/",
            "github.com/digitaltwin-run/",
            "github.com/maskservice/",
            "github.com/autogrammar/",
            "github.com/subactor/",
            "github.com/twinerd/",
            "github.com/clonerd-com/",
            "github.com/wronai/",
            "github.com/pactown-com/"
        )
        return not any(org in url for org in user_orgs)
    except Exception:
        return False


def discover_repositories(root: Path, orgs: List[str] | None = None) -> List[Path]:
    """Discover user-authored candidate repositories."""
    repos = []
    if not root.is_dir():
        return repos

    for org_dir in sorted(root.iterdir()):
        if not org_dir.is_dir() or org_dir.name.startswith("."):
            continue
        if orgs and org_dir.name not in orgs:
            continue
        for repo_dir in sorted(org_dir.iterdir()):
            if repo_dir.is_dir() and not repo_dir.name.startswith(".") and is_git_repo(repo_dir):
                if not is_fork(repo_dir):
                    repos.append(repo_dir)
    return repos


def audit_repository(repo_path: Path) -> Dict[str, Any]:
    """Run conformance audit on one repository."""
    conf = run_conformance(repo_path)
    return {
        "repo": f"{repo_path.parent.name}/{repo_path.name}",
        "path": str(repo_path),
        "conformance": conf.to_dict(),
        "passed": conf.passed
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fleet-wide Wellmanifest Reuse & Docs Auditor")
    default_root = Path(os.environ.get("WORKSPACE_ROOT") or (Path.home() / "github"))
    parser.add_argument("--root", type=Path, default=default_root, help="Workspace root")
    parser.add_argument("--orgs", type=str, default="digitaltwin-run,paxlet-com,wellmanifest,semcod", help="Comma-separated orgs to audit")
    parser.add_argument("--limit", type=int, default=10, help="Max repos to inspect")
    parser.add_argument("--apply-plan", action="store_true", help="Generate planfile reuse & docs tasks for failing repos")
    parser.add_argument("--run-koru", action="store_true", help="Execute one autonomous koru step per repository")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    selected_orgs = [o.strip() for o in args.orgs.split(",") if o.strip()]
    repos = discover_repositories(args.root, orgs=selected_orgs)[:args.limit]

    print(f"🌐 Discovered {len(repos)} candidate repositories across orgs: {selected_orgs}")
    results = []
    
    for repo in repos:
        audit_data = audit_repository(repo)
        results.append(audit_data)
        status_icon = "✅" if audit_data["passed"] else "⚠️"
        print(f" {status_icon} {audit_data['repo']}: {'Conforming' if audit_data['passed'] else 'Needs Docs/Planfile Alignment'}")

        if args.apply_plan and not audit_data["passed"]:
            tasks, tickets = create_reuse_plan_data(repo, topic=repo.name)
            sprint_file = repo / ".planfile" / "sprints" / "current.yaml"
            update_planfile_sprint(sprint_file, tasks, tickets)

        if args.run_koru:
            try:
                cmd = [sys.executable, "-m", "koru", "--queue", "--project", str(repo)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    print(f"   🤖 Koru autonomous execution completed on {audit_data['repo']}")
            except Exception as exc:
                print(f"   ⚠️ Koru run skipped or timed out on {audit_data['repo']}: {exc}")

    if args.json:
        print(json.dumps(results, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
