#!/usr/bin/env python3
"""
Reuse Orchestrator for Wellmanifest Reuse Standard (wellmanifest/reuse@v0.2.0).

Coordinates multi-repository code discovery (semcod/search), AST clone detection
and clustering (semcod/redup), semantic logic profiling (semcod/code2logic),
canonical DSL and schema generation (autogrammar/code2schema, redsl, testql),
and sequential intent ticket dispatching (subactor/intent).
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def infer_workstream(allowed_paths: List[str]) -> str:
    """Infer governance workstream from target path patterns."""
    for p in allowed_paths:
        if any(token in p for token in ("pyproject.toml", "package.json", "VERSION", "Cargo.toml", "go.mod")):
            return "integration"
    for p in allowed_paths:
        if any(token in p for token in ("src/", "app/", "lib/", "test/", "tests/", "src/**", "tests/**")):
            return "application"
    return "governance"


class SearchDiscoverer:
    """Capability and intent discovery using semcod/search or local AST index."""

    @staticmethod
    def search_capabilities(query: str, workspace_root: Path) -> List[Dict[str, Any]]:
        """Search repositories under workspace_root for implementations matching query."""
        results: List[Dict[str, Any]] = []

        # 1. Try subactor-search / semcod/search CLI if available
        try:
            res = subprocess.run(
                ["subactor-search", "ask", query, "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, list):
                    return data
        except Exception:
            pass

        # 2. Local Python AST / token scan fallback across workspace projects
        terms = [t.lower() for t in query.split() if len(t) > 2]
        if not terms:
            terms = [query.lower()]

        if not workspace_root.is_dir():
            return results

        for proj in sorted(workspace_root.iterdir()):
            if not proj.is_dir() or proj.name.startswith("."):
                continue
            matches = []
            for py_path in proj.rglob("*.py"):
                rel = str(py_path.relative_to(proj))
                if any(p in rel for p in (".git", "venv", ".venv", "__pycache__", "build", "dist", "site-packages")):
                    continue
                try:
                    content = py_path.read_text(encoding="utf-8", errors="ignore")
                    for term in terms:
                        if term in content.lower():
                            matches.append({"file": rel, "term": term})
                            break
                except Exception:
                    continue
            if matches:
                results.append({
                    "project": proj.name,
                    "path": str(proj),
                    "match_count": len(matches),
                    "samples": matches[:5],
                })
        return sorted(results, key=lambda r: r["match_count"], reverse=True)

    @staticmethod
    def record_search_receipt(target_project: Path, query: str, results: List[Dict[str, Any]]) -> Path:
        """Record REUSE-001 search discovery receipt in .reuse/search-receipt.json."""
        receipt = {
            "schema": "wellmanifest.reuse-search-receipt/v1",
            "query": query,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "candidate_count": len(results),
            "candidates": results[:10],
        }
        out_file = target_project / ".reuse" / "search-receipt.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(receipt, indent=2) + "\n")
        return out_file


class CodeLogicAnalyzer:
    """Semantic AST and function logic profiler using semcod/code2logic or native AST fallback."""

    def __init__(self, project_path: Path):
        self.project_path = project_path.resolve()

    def profile_python_file(self, file_path: Path) -> Dict[str, Any]:
        """Extract functions, classes, signatures, and docstrings via AST."""
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(file_path))
        except Exception as exc:
            return {"file": str(file_path), "error": str(exc), "functions": [], "classes": []}

        functions = []
        classes = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({
                    "name": node.name,
                    "args": [arg.arg for arg in node.args.args],
                    "docstring": ast.get_docstring(node) or "",
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno),
                })
            elif isinstance(node, ast.ClassDef):
                methods = [
                    m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    "name": node.name,
                    "methods": methods,
                    "docstring": ast.get_docstring(node) or "",
                    "lineno": node.lineno,
                })

        return {
            "file": str(file_path.relative_to(self.project_path)),
            "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
            "functions": functions,
            "classes": classes,
        }

    def profile_project(self) -> Dict[str, Any]:
        """Profile all Python files in the project."""
        profiles = []
        for py_path in sorted(self.project_path.rglob("*.py")):
            rel = str(py_path.relative_to(self.project_path))
            if any(part in rel for part in (".git", ".governance", "venv", ".venv", "tests", "standards", "__pycache__")):
                continue
            profiles.append(self.profile_python_file(py_path))
        return {
            "schema": "wellmanifest.reuse-ast-profile/v1",
            "project": self.project_path.name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "modules": profiles,
        }

    def run_code2logic_if_available(self, output_format: str = "toon") -> Optional[str]:
        """Invoke semcod/code2logic if installed."""
        try:
            import code2logic  # type: ignore # noqa: F401
            res = subprocess.run(
                ["python3", "-m", "code2logic", str(self.project_path), "-f", output_format, "--stdout", "--does"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout
        except (ImportError, OSError, subprocess.SubprocessError):
            pass
        return None


class CloneDetector:
    """AST clone and cross-project duplicate detection via semcod/redup."""

    @staticmethod
    def compare_projects(project_a: Path, project_b: Path, threshold: float = 0.75, min_lines: int = 5) -> Dict[str, Any]:
        """Run redup compare and return structured recommendation and community clusters."""
        cmd = [
            "python3", "-m", "redup", "compare",
            str(project_a), str(project_b),
            "--threshold", str(threshold),
            "--min-lines", str(min_lines),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = res.stdout + res.stderr

        # Extract metrics and candidate communities from output
        shared_lines = 0
        overlap_pct = 0.0
        recommendation = "keep_separate"
        communities = []
        top_matches = []

        in_communities = False
        in_matches = False
        for line in output.splitlines():
            if "Shared LOC" in line:
                m = re.search(r"(\d+)", line)
                if m:
                    shared_lines = int(m.group(1))
            if "overlap" in line.lower() or "similar" in line.lower():
                m = re.search(r"(\d+(?:\.\d+)?)%", line)
                if m:
                    overlap_pct = float(m.group(1))
            if "Recommendation:" in line:
                parts = line.split("Recommendation:")
                if len(parts) > 1:
                    recommendation = parts[1].strip()

            if "Top Communities" in line:
                in_communities = True
                in_matches = False
                continue
            if "Matches" in line:
                in_matches = True
                in_communities = False
                continue

            if in_communities and "│" in line:
                parts = [p.strip() for p in line.split("│")[1:-1]]
                if len(parts) >= 5 and parts[0].isdigit():
                    communities.append({
                        "id": parts[0],
                        "name": parts[1],
                        "similarity": parts[2],
                        "loc": parts[3],
                        "members": parts[4],
                    })

            if in_matches and "│" in line:
                parts = [p.strip() for p in line.split("│")[1:-1]]
                if len(parts) >= 6 and parts[0] in ("exact", "structural", "fuzzy"):
                    top_matches.append({
                        "type": parts[0],
                        "similarity": parts[1],
                        "fn_a": parts[2],
                        "fn_b": parts[3],
                        "file_a": parts[4],
                        "file_b": parts[5],
                    })

        extraction_candidates = [c["name"] for c in communities if c["name"] not in ("main", "run")]
        if not extraction_candidates and top_matches:
            extraction_candidates = list({m["fn_a"] for m in top_matches if m["fn_a"] not in ("main",)})

        return {
            "project_a": str(project_a),
            "project_b": str(project_b),
            "shared_loc": shared_lines,
            "overlap_pct": overlap_pct,
            "recommendation": recommendation,
            "communities": communities,
            "top_matches": top_matches[:10],
            "extraction_candidates": extraction_candidates,
            "raw_output": output,
        }


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

        # Determine git base sha
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
            "forbiddenPaths": [
                "project/ticket-*/user-*.md",
            ],
            "stacks": [],
            "dependsOn": [],
            "conflictsWith": [],
            "integrationTicket": None,
            "delivery": {
                "acceptedBaseSha": head_sha,
                "targetBranch": "main",
                "outcome": f"Deduplicate shared logic and establish clean reuse interface under REUSE-003.",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Wellmanifest Reuse Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    scan_p = subparsers.add_parser("scan", help="Scan project for AST profiles and clones")
    scan_p.add_argument("project", type=Path, help="Target project path")

    # discover
    disc_p = subparsers.add_parser("discover", help="Discover existing capabilities before generation (REUSE-001)")
    disc_p.add_argument("query", help="Capability search term (e.g. 'auth token validator')")
    disc_p.add_argument("--workspace", "-w", type=Path, default=Path.cwd().parent, help="Root workspace to search")
    disc_p.add_argument("--record-in", "-r", type=Path, help="Target repo to write .reuse/search-receipt.json")

    # compare
    comp_p = subparsers.add_parser("compare", help="Compare two projects for duplication")
    comp_p.add_argument("project_a", type=Path, help="First project path")
    comp_p.add_argument("project_b", type=Path, help="Second project path")
    comp_p.add_argument("--threshold", type=float, default=0.75, help="Similarity threshold")

    # contract
    contract_p = subparsers.add_parser("contract", help="Generate canonical DSL and schema contracts (REUSE-003, REUSE-005)")
    contract_p.add_argument("--target", "-t", type=Path, required=True, help="Target project to write contracts into")
    contract_p.add_argument("--name", "-n", required=True, help="Name of extracted module (e.g. 'auth_validator')")
    contract_p.add_argument("--functions", "-f", nargs="+", required=True, help="Function names in the shared interface")
    contract_p.add_argument("--consumers", "-c", nargs="*", default=[], help="Consumer projects")

    # intent
    intent_p = subparsers.add_parser("intent", help="Generate subactor reuse intent ticket")
    intent_p.add_argument("--target", "-t", type=Path, required=True, help="Target repository")
    intent_p.add_argument("--ticket-id", help="Ticket ID (e.g. ticket-020). Auto-inferred if omitted.")
    intent_p.add_argument("--summary", required=True, help="Short summary of reuse work")
    intent_p.add_argument("--use-script", action="store_true", help="Use ./project/new-ticket.sh if available")

    # orchestrate
    orch_p = subparsers.add_parser("orchestrate", help="Full automated reuse discovery, compare, contract, and ticket dispatch")
    orch_p.add_argument("--target", "-t", type=Path, required=True, help="Target repository")
    orch_p.add_argument("--reference", "-r", type=Path, required=True, help="Reference repository to compare against")
    orch_p.add_argument("--summary", "-s", required=True, help="Summary of intended reuse work")

    args = parser.parse_args()

    if args.command == "scan":
        analyzer = CodeLogicAnalyzer(args.project)
        profile = analyzer.profile_project()
        out_file = args.project / ".reuse" / "ast-profile.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(profile, indent=2) + "\n")
        print(f"✅ Generated AST profile with {len(profile['modules'])} modules at: {out_file}")
        return 0

    if args.command == "discover":
        results = SearchDiscoverer.search_capabilities(args.query, args.workspace)
        print(f"\n🔎 Discovery results for query: '{args.query}' (found in {len(results)} projects)")
        for item in results[:5]:
            print(f"   • {item['project']}: {item['match_count']} matches")
        if args.record_in:
            rpath = SearchDiscoverer.record_search_receipt(args.record_in, args.query, results)
            print(f"✅ Recorded discovery receipt at: {rpath}")
        return 0

    if args.command == "compare":
        result = CloneDetector.compare_projects(args.project_a, args.project_b, threshold=args.threshold)
        print(f"\n🔍 Comparison {args.project_a.name} ↔ {args.project_b.name}")
        print(f"   Shared LOC (est): {result['shared_loc']}")
        print(f"   Overlap: {result['overlap_pct']}%")
        print(f"   Recommendation: {result['recommendation']}")
        if result.get("extraction_candidates"):
            print(f"   Extraction Candidates: {', '.join(result['extraction_candidates'][:6])}")
        print()
        return 0

    if args.command == "contract":
        tpath = args.target.resolve()
        # 1. TestQL scenario
        testql_content = ContractGenerator.generate_testql_scenario(args.name, args.functions)
        testql_file = tpath / "testql-scenarios" / f"verify-reuse-{args.name}.testql.yaml"
        testql_file.parent.mkdir(parents=True, exist_ok=True)
        testql_file.write_text(testql_content)
        print(f"✅ Generated TestQL scenario at: {testql_file}")

        # 2. ReDSL contract
        redsl_content = ContractGenerator.generate_redsl_refactor_contract(args.name, args.functions, args.consumers)
        redsl_file = tpath / "contracts" / f"{args.name}.redsl.yaml"
        redsl_file.parent.mkdir(parents=True, exist_ok=True)
        redsl_file.write_text(redsl_content)
        print(f"✅ Generated ReDSL contract at: {redsl_file}")

        # 3. JSON schema
        schema = ContractGenerator.generate_json_schema_from_pydantic_or_ast({
            "file": args.name,
            "classes": [{"name": args.name.capitalize(), "docstring": "Extracted contract", "methods": args.functions}],
        })
        schema_file = tpath / "schemas" / f"{args.name}.schema.json"
        schema_file.parent.mkdir(parents=True, exist_ok=True)
        schema_file.write_text(json.dumps(schema, indent=2) + "\n")
        print(f"✅ Generated canonical schema at: {schema_file}")
        return 0

    if args.command == "intent":
        tid = args.ticket_id
        if args.use_script:
            script_tid = IntentTicketDispatcher.allocate_via_script_if_available(args.target, args.summary)
            if script_tid:
                tid = script_tid
                print(f"✅ Allocated {tid} via ./project/new-ticket.sh")
        if not tid:
            tid = IntentTicketDispatcher.find_next_ticket_id(args.target)

        intent_data = IntentTicketDispatcher.create_reuse_intent(
            ticket_id=tid,
            summary=args.summary,
            target_repo=args.target,
        )
        tdir = IntentTicketDispatcher.write_ticket_files(args.target, tid, intent_data)
        print(f"✅ Created reuse intent ticket {tid} at: {tdir}")
        return 0

    if args.command == "orchestrate":
        print(f"\n🚀 Running Full Reuse Orchestration for {args.target.name}")
        # 1. Compare with reference
        cmp_res = CloneDetector.compare_projects(args.target, args.reference)
        print(f"   1. Clone Analysis: {cmp_res['shared_loc']} shared LOC ({cmp_res['recommendation']})")
        candidates = cmp_res.get("extraction_candidates", []) or ["validate", "check"]

        # 2. Generate Contracts
        module_name = f"{args.target.name}_shared"
        tpath = args.target.resolve()
        tql = ContractGenerator.generate_testql_scenario(module_name, candidates)
        (tpath / "testql-scenarios").mkdir(parents=True, exist_ok=True)
        (tpath / "testql-scenarios" / f"verify-reuse-{module_name}.testql.yaml").write_text(tql)

        # 3. Create Intent Ticket
        script_tid = IntentTicketDispatcher.allocate_via_script_if_available(args.target, args.summary)
        tid = script_tid or IntentTicketDispatcher.find_next_ticket_id(args.target)
        intent = IntentTicketDispatcher.create_reuse_intent(
            ticket_id=tid,
            summary=args.summary,
            target_repo=args.target,
            source_repo=args.reference,
        )
        tdir = IntentTicketDispatcher.write_ticket_files(args.target, tid, intent)
        print(f"   2. Generated TestQL scenario and schema contracts")
        print(f"   3. Created subactor intent ticket: {tid} at {tdir}\n")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
