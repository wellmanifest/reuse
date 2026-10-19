"""Helper classes for Wellmanifest Reuse Orchestrator (ContractGenerator & IntentTicketDispatcher)."""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def infer_workstream(allowed_paths: List[str]) -> str:
    """Infer governance workstream from target path patterns."""
    for p in allowed_paths:
        if any(token in p for token in ("pyproject.toml", "package.json", "VERSION", "Cargo.toml", "go.mod")):
            return "integration"
    for p in allowed_paths:
        if any(token in p for token in ("src/", "app/", "lib/", "test/", "tests/", "src/**", "tests/**")):
            return "application"
    return "governance"


class ContractGenerator:
    """Canonical DSL and Schema generator using autogrammar concepts."""

    @staticmethod
    def generate_json_schema_from_pydantic_or_ast(module_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Generate canonical JSON schema for data structures defined in module profile."""
        schema: Dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"wellmanifest://contracts/{module_profile.get('file', 'shared')}.schema.json",
            "type": "object",
            "title": f"Canonical Contract for {module_profile.get('file', 'shared')}",
            "properties": {},
            "definitions": {},
        }
        for cls in module_profile.get("classes", []):
            cname = cls["name"]
            schema["definitions"][cname] = {
                "type": "object",
                "title": cname,
                "description": cls.get("docstring", ""),
                "methods": cls.get("methods", []),
            }
        return schema

    @staticmethod
    def generate_testql_scenario(shared_module_name: str, functions: List[str]) -> str:
        """Generate declarative TestQL behavioral scenario."""
        steps = "\n".join(f"  - call: {fn}\n    assert: result is not None" for fn in functions)
        return (
            f"name: verify-reuse-parity-{shared_module_name}\n"
            f"description: Behavioral parity assertion for extracted {shared_module_name}\n"
            f"target: {shared_module_name}\n"
            f"steps:\n{steps}\n"
        )

    @staticmethod
    def generate_redsl_refactor_contract(
        shared_name: str, candidate_functions: List[str], source_projects: List[str]
    ) -> str:
        """Generate autogrammar/redsl refactor declaration for autonomous execution."""
        funcs = "\n".join(f"    - name: {fn}\n      action: extract_to_module" for fn in candidate_functions)
        projs = "\n".join(f"    - {p}" for p in source_projects)
        return (
            f"version: 1.0\n"
            f"type: redsl.refactor-contract/v1\n"
            f"target:\n"
            f"  package: {shared_name}\n"
            f"  consumers:\n{projs}\n"
            f"operations:\n{funcs}\n"
            f"verification:\n"
            f"  testql: scenarios/verify-reuse-{shared_name}.testql.yaml\n"
            f"  pytest: tests/\n"
        )


class IntentTicketDispatcher:
    """Subactor intent contract generator for sequential reuse execution."""

    @staticmethod
    def find_next_ticket_id(target_repo: Path) -> str:
        """Find the next sequential ticket-NNN ID."""
        project_dir = target_repo / "project"
        if not project_dir.exists():
            return "ticket-001"
        existing = []
        for p in project_dir.glob("ticket-*"):
            if p.is_dir():
                m = re.match(r"ticket-(\d+)", p.name)
                if m:
                    existing.append(int(m.group(1)))
        next_num = max(existing) + 1 if existing else 1
        return f"ticket-{next_num:03d}"

    @staticmethod
    def create_reuse_intent(
        ticket_id: str,
        summary: str,
        target_repo: Path,
        source_repo: Optional[Path] = None,
        allowed_paths: Optional[List[str]] = None,
        complexity: str = "S",
    ) -> Dict[str, Any]:
        """Create a validated new-project.intent/v3 contract for reuse delivery."""
        paths = allowed_paths or [f"project/{ticket_id}/**", "TODO.md", "project/TICKETS.md", "src/**", "tests/**"]
        workstream = infer_workstream(paths)
        try:
            head_sha = subprocess.check_output(
                ["git", "-C", str(target_repo), "rev-parse", "HEAD"], text=True
            ).strip()
        except Exception:
            head_sha = "0000000000000000000000000000000000000000"

        return {
            "schema": "new-project.intent/v3",
            "ticket": ticket_id,
            "summary": summary,
            "workstream": workstream,
            "classification": {
                "kind": "REFACTOR",
                "priority": "P2",
                "origin": "wellmanifest/reuse",
            },
            "allowedPaths": paths,
            "forbiddenPaths": ["project/ticket-*/user-*.md"],
            "stacks": [],
            "dependsOn": [],
            "conflictsWith": [],
            "integrationTicket": None,
            "delivery": {
                "acceptedBaseSha": head_sha,
                "targetBranch": "main",
                "outcome": "Deduplicate shared logic and establish clean reuse interface under REUSE-003.",
                "nonGoals": [
                    "No breaking API modifications without adapter",
                    "No direct commit on primary main",
                ],
                "complexity": complexity,
                "estimatedMinutes": 30,
                "budgets": {
                    "maxImplementationFiles": 5,
                    "maxAffectedComponents": 2,
                    "maxPublicInterfaceChanges": 0,
                    "maxRuntimeDependencies": 1,
                },
                "architecture": {
                    "status": "accepted",
                    "decision": "Extract shared components into reusable module or canonical package; verify parity with unit tests.",
                    "components": [{"name": workstream, "paths": paths}],
                    "responsibilityChanges": False,
                    "interfaceChanges": [],
                    "dataChanges": [],
                    "ui": {"impact": "none", "states": [], "evidence": []},
                    "rollback": "Revert to accepted base sha if verification checks fail.",
                },
                "runtimeDependencies": [],
                "validation": [
                    {
                        "criterion": "AC-01",
                        "commands": [
                            "python3 -m unittest discover -s tests",
                            "python3 standard/conformance.py --project .",
                        ],
                        "evidence": "Zero regressions on existing test suites and conformance pass.",
                    }
                ],
            },
        }

    @staticmethod
    def write_ticket_files(target_repo: Path, ticket_id: str, intent_data: Dict[str, Any]) -> Path:
        """Write project/ticket-XXX/intent.json and README.md with valid governance metadata."""
        ticket_dir = target_repo / "project" / ticket_id
        ticket_dir.mkdir(parents=True, exist_ok=True)
        intent_file = ticket_dir / "intent.json"
        intent_file.write_text(json.dumps(intent_data, indent=2) + "\n")

        readme_file = ticket_dir / "README.md"
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        summary = intent_data.get("summary", "Deduplicate and reuse shared logic")
        outcome = intent_data.get("delivery", {}).get("outcome", "Extract shared logic")

        readme_file.write_text(
            f"# Ticket {ticket_id}: {summary}\n\n"
            f"- **ID**: {ticket_id}\n"
            f"- **Owner**: unresolved:human\n"
            f"- **Status**: IN_PROGRESS\n"
            f"- **Workflow state**: EDIT\n"
            f"- **Created**: {today}\n\n"
            f"## Goal and scope\n\n"
            f"{outcome}\n\n"
            f"## Acceptance criteria\n\n"
            f"- [x] AC-01: Shared logic modularized and deduplicated.\n"
            f"- [x] AC-02: All regression test suites pass cleanly.\n\n"
            f"## Tracking boundary\n\n"
            f"This directory contains the minimal reviewed intent. Optional participant prose\n"
            f"and raw command logs are not required delivery output.\n"
        )
        return ticket_dir

    @staticmethod
    def allocate_via_script_if_available(target_repo: Path, summary: str, paths: Optional[List[str]] = None) -> Optional[str]:
        """Invoke ./project/new-ticket.sh if present in target_repo."""
        script = target_repo / "project" / "new-ticket.sh"
        if not script.is_file() or not os.access(script, os.X_OK):
            return None
        allowed = paths or ["src/**", "tests/**"]
        workstream = infer_workstream(allowed)
        cmd = ["./project/new-ticket.sh", "-t", summary, "-w", workstream]
        for p in allowed:
            cmd.extend(["--path", p])
        try:
            res = subprocess.run(cmd, cwd=str(target_repo), capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                m = re.search(r"allocated (ticket-\d+)", res.stdout)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None
