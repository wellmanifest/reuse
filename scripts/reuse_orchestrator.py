#!/usr/bin/env python3
"""
Reuse Orchestrator for Wellmanifest Reuse Standard (wellmanifest/reuse@v0.4.0).

Coordinates multi-repository code discovery (semcod/search), AST clone detection
and clustering (semcod/redup), semantic logic profiling (semcod/code2logic),
canonical DSL and schema generation (autogrammar/code2schema, redsl, testql),
and sequential intent ticket dispatching (subactor/intent) via StreamPipeline.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from reuse_orchestrator_helpers import ContractGenerator, IntentTicketDispatcher, infer_workstream
from standard.stream_flow import DependencyResolver, PrioritizedDependency, StreamPipeline, StreamStage


class SearchDiscoverer:
    """Capability and intent discovery using PrioritizedDependency (semcod/search -> local AST scan)."""

    @staticmethod
    def _subactor_search(query: str, workspace_root: Path) -> List[Dict[str, Any]]:
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
        raise RuntimeError("subactor-search returned no list")

    @staticmethod
    def _local_ast_scan(query: str, workspace_root: Path) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        terms = [t.lower() for t in query.split() if len(t) > 2] or [query.lower()]
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
                    content = py_path.read_text(encoding="utf-8", errors="ignore").lower()
                    for term in terms:
                        if term in content:
                            matches.append({"file": rel, "term": term})
                            break
                except Exception:
                    continue
            if matches:
                results.append({"project": proj.name, "path": str(proj), "match_count": len(matches), "samples": matches[:5]})
        return sorted(results, key=lambda r: r["match_count"], reverse=True)

    @classmethod
    def search_capabilities(cls, query: str, workspace_root: Path) -> List[Dict[str, Any]]:
        """Search repositories under workspace_root using prioritized provider chain (REUSE-017)."""
        resolver = DependencyResolver([
            PrioritizedDependency(
                id="subactor-search-cli",
                capability="search_capabilities",
                tier="floor",
                weight=100.0,
                provider=cls._subactor_search,
                fallback_id="local-ast-scan",
            ),
            PrioritizedDependency(
                id="local-ast-scan",
                capability="search_capabilities",
                tier="standard",
                weight=10.0,
                provider=cls._local_ast_scan,
            ),
        ])
        return resolver.resolve("search_capabilities", query, workspace_root).value

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
                methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
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

        shared_lines = 0
        overlap_pct = 0.0
        recommendation = "keep_separate"
        communities = []
        top_matches = []
        section = ""

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
                section = "communities"
                continue
            if "Matches" in line:
                section = "matches"
                continue
            if section == "communities" and "│" in line:
                parts = [p.strip() for p in line.split("│")[1:-1]]
                if len(parts) >= 5 and parts[0].isdigit():
                    communities.append({"id": parts[0], "name": parts[1], "similarity": parts[2], "loc": parts[3], "members": parts[4]})
            elif section == "matches" and "│" in line:
                parts = [p.strip() for p in line.split("│")[1:-1]]
                if len(parts) >= 6 and parts[0] in ("exact", "structural", "fuzzy"):
                    top_matches.append({"type": parts[0], "similarity": parts[1], "fn_a": parts[2], "fn_b": parts[3], "file_a": parts[4], "file_b": parts[5]})

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


def _cmd_scan(args: argparse.Namespace) -> int:
    analyzer = CodeLogicAnalyzer(args.project)
    profile = analyzer.profile_project()
    out_file = args.project / ".reuse" / "ast-profile.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"✅ Generated AST profile with {len(profile['modules'])} modules at: {out_file}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    results = SearchDiscoverer.search_capabilities(args.query, args.workspace)
    print(f"\n🔎 Discovery results for query: '{args.query}' (found in {len(results)} projects)")
    for item in results[:5]:
        print(f"   • {item['project']}: {item['match_count']} matches")
    if args.record_in:
        rpath = SearchDiscoverer.record_search_receipt(args.record_in, args.query, results)
        print(f"✅ Recorded discovery receipt at: {rpath}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    result = CloneDetector.compare_projects(args.project_a, args.project_b, threshold=args.threshold)
    print(f"\n🔍 Comparison {args.project_a.name} ↔ {args.project_b.name}")
    print(f"   Shared LOC (est): {result['shared_loc']}")
    print(f"   Overlap: {result['overlap_pct']}%")
    print(f"   Recommendation: {result['recommendation']}")
    if result.get("extraction_candidates"):
        print(f"   Extraction Candidates: {', '.join(result['extraction_candidates'][:6])}")
    print()
    return 0


def _cmd_contract(args: argparse.Namespace) -> int:
    tpath = args.target.resolve()
    testql_file = tpath / "testql-scenarios" / f"verify-reuse-{args.name}.testql.yaml"
    testql_file.parent.mkdir(parents=True, exist_ok=True)
    testql_file.write_text(ContractGenerator.generate_testql_scenario(args.name, args.functions))
    print(f"✅ Generated TestQL scenario at: {testql_file}")

    redsl_file = tpath / "contracts" / f"{args.name}.redsl.yaml"
    redsl_file.parent.mkdir(parents=True, exist_ok=True)
    redsl_file.write_text(ContractGenerator.generate_redsl_refactor_contract(args.name, args.functions, args.consumers))
    print(f"✅ Generated ReDSL contract at: {redsl_file}")

    schema = ContractGenerator.generate_json_schema_from_pydantic_or_ast({
        "file": args.name,
        "classes": [{"name": args.name.capitalize(), "docstring": "Extracted contract", "methods": args.functions}],
    })
    schema_file = tpath / "schemas" / f"{args.name}.schema.json"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    schema_file.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"✅ Generated canonical schema at: {schema_file}")
    return 0


def _cmd_intent(args: argparse.Namespace) -> int:
    tid = args.ticket_id
    if args.use_script:
        script_tid = IntentTicketDispatcher.allocate_via_script_if_available(args.target, args.summary)
        if script_tid:
            tid = script_tid
            print(f"✅ Allocated {tid} via ./project/new-ticket.sh")
    if not tid:
        tid = IntentTicketDispatcher.find_next_ticket_id(args.target)
    intent_data = IntentTicketDispatcher.create_reuse_intent(ticket_id=tid, summary=args.summary, target_repo=args.target)
    tdir = IntentTicketDispatcher.write_ticket_files(args.target, tid, intent_data)
    print(f"✅ Created reuse intent ticket {tid} at: {tdir}")
    return 0


def _cmd_orchestrate(args: argparse.Namespace) -> int:
    print(f"\n🚀 Running Full Reuse Orchestration for {args.target.name}")
    pipeline = StreamPipeline("reuse.orchestrate", [
        StreamStage(
            id="compare-clones",
            kind="module",
            tier="floor",
            weight=100.0,
            transform=lambda env: {**env.payload, "cmp": CloneDetector.compare_projects(env.payload["target"], env.payload["reference"])},
        ),
        StreamStage(
            id="generate-contracts",
            kind="component",
            tier="standard",
            weight=80.0,
            depends_on=("compare-clones",),
            transform=lambda env: _orchestrate_contracts_step(env.payload),
        ),
        StreamStage(
            id="dispatch-intent",
            kind="process",
            tier="standard",
            weight=60.0,
            depends_on=("generate-contracts",),
            transform=lambda env: _orchestrate_intent_step(env.payload),
        ),
    ])
    for final_env in pipeline.stream([{"target": args.target, "reference": args.reference, "summary": args.summary}]):
        state = final_env.payload
        print(f"   1. Clone Analysis: {state['cmp']['shared_loc']} shared LOC ({state['cmp']['recommendation']})")
        print("   2. Generated TestQL scenario and schema contracts")
        print(f"   3. Created subactor intent ticket: {state['tid']} at {state['tdir']}\n")
    return 0


def _orchestrate_contracts_step(state: Dict[str, Any]) -> Dict[str, Any]:
    target: Path = state["target"]
    candidates = state["cmp"].get("extraction_candidates", []) or ["validate", "check"]
    module_name = f"{target.name}_shared"
    tpath = target.resolve()
    tql = ContractGenerator.generate_testql_scenario(module_name, candidates)
    (tpath / "testql-scenarios").mkdir(parents=True, exist_ok=True)
    (tpath / "testql-scenarios" / f"verify-reuse-{module_name}.testql.yaml").write_text(tql)
    return {**state, "candidates": candidates, "module_name": module_name}


def _orchestrate_intent_step(state: Dict[str, Any]) -> Dict[str, Any]:
    target: Path = state["target"]
    summary: str = state["summary"]
    tid = IntentTicketDispatcher.allocate_via_script_if_available(target, summary) or IntentTicketDispatcher.find_next_ticket_id(target)
    intent = IntentTicketDispatcher.create_reuse_intent(ticket_id=tid, summary=summary, target_repo=target, source_repo=state["reference"])
    tdir = IntentTicketDispatcher.write_ticket_files(target, tid, intent)
    return {**state, "tid": tid, "tdir": tdir}


COMMAND_HANDLERS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "scan": _cmd_scan,
    "discover": _cmd_discover,
    "compare": _cmd_compare,
    "contract": _cmd_contract,
    "intent": _cmd_intent,
    "orchestrate": _cmd_orchestrate,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Wellmanifest Reuse Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_p = subparsers.add_parser("scan", help="Scan project for AST profiles and clones")
    scan_p.add_argument("project", type=Path, help="Target project path")

    disc_p = subparsers.add_parser("discover", help="Discover existing capabilities before generation (REUSE-001)")
    disc_p.add_argument("query", help="Capability search term (e.g. 'auth token validator')")
    disc_p.add_argument("--workspace", "-w", type=Path, default=Path.cwd().parent, help="Root workspace to search")
    disc_p.add_argument("--record-in", "-r", type=Path, help="Target repo to write .reuse/search-receipt.json")

    comp_p = subparsers.add_parser("compare", help="Compare two projects for duplication")
    comp_p.add_argument("project_a", type=Path, help="First project path")
    comp_p.add_argument("project_b", type=Path, help="Second project path")
    comp_p.add_argument("--threshold", type=float, default=0.75, help="Similarity threshold")

    contract_p = subparsers.add_parser("contract", help="Generate canonical DSL and schema contracts (REUSE-003, REUSE-005)")
    contract_p.add_argument("--target", "-t", type=Path, required=True, help="Target project to write contracts into")
    contract_p.add_argument("--name", "-n", required=True, help="Name of extracted module (e.g. 'auth_validator')")
    contract_p.add_argument("--functions", "-f", nargs="+", required=True, help="Function names in the shared interface")
    contract_p.add_argument("--consumers", "-c", nargs="*", default=[], help="Consumer projects")

    intent_p = subparsers.add_parser("intent", help="Generate subactor reuse intent ticket")
    intent_p.add_argument("--target", "-t", type=Path, required=True, help="Target repository")
    intent_p.add_argument("--ticket-id", help="Ticket ID (e.g. ticket-020). Auto-inferred if omitted.")
    intent_p.add_argument("--summary", required=True, help="Short summary of reuse work")
    intent_p.add_argument("--use-script", action="store_true", help="Use ./project/new-ticket.sh if available")

    orch_p = subparsers.add_parser("orchestrate", help="Full automated reuse discovery, compare, contract, and ticket dispatch")
    orch_p.add_argument("--target", "-t", type=Path, required=True, help="Target repository")
    orch_p.add_argument("--reference", "-r", type=Path, required=True, help="Reference repository to compare against")
    orch_p.add_argument("--summary", "-s", required=True, help="Summary of intended reuse work")

    args = parser.parse_args()
    handler = COMMAND_HANDLERS.get(args.command)
    return handler(args) if handler is not None else 0


if __name__ == "__main__":
    sys.exit(main())
