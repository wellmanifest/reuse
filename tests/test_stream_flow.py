"""Tests for Wellmanifest Stream Flow, DecisionEngine, DependencyResolver, and Horizontal Complexity (REUSE-015..018)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from standard.stream_flow import (
    DecisionEngine,
    DecisionRule,
    DependencyResolver,
    PrioritizedDependency,
    StreamEnvelope,
    StreamPipeline,
    StreamStage,
    analyze_horizontal_complexity,
)


def test_decision_engine_lexicographic_tiers_and_satisfied_when():
    rules = [
        DecisionRule(
            id="opt-high-weight",
            tier="opportunistic",
            weight=999.0,
            outcome="use_opportunistic",
            when=lambda ctx: True,
        ),
        DecisionRule(
            id="std-medium",
            tier="standard",
            weight=50.0,
            outcome="use_standard",
            when=lambda ctx: ctx.get("ready", False),
        ),
        DecisionRule(
            id="floor-safety",
            tier="floor",
            weight=1.0,
            outcome="enforce_safety",
            when=lambda ctx: ctx.get("unsafe", False),
            satisfied_when=lambda ctx: ctx.get("safety_verified", False),
        ),
    ]
    engine = DecisionEngine(rules, default_outcome="fallback")

    # 1. Floor rule always wins over higher numeric weights when matched and not yet satisfied
    trace1 = engine.decide({"unsafe": True, "ready": True})
    assert trace1.selected_id == "floor-safety"
    assert trace1.outcome == "enforce_safety"
    assert trace1.tier == "floor"

    # 2. When floor rule is already satisfied, standard tier wins over opportunistic (even with weight 999)
    trace2 = engine.decide({"unsafe": True, "safety_verified": True, "ready": True})
    assert trace2.selected_id == "std-medium"
    assert trace2.outcome == "use_standard"

    # 3. When standard rule predicate is False, opportunistic rule is selected
    trace3 = engine.decide({"unsafe": False, "ready": False})
    assert trace3.selected_id == "opt-high-weight"
    assert trace3.outcome == "use_opportunistic"


def test_dependency_resolver_prioritized_fallback_chain():
    resolver = DependencyResolver([
        PrioritizedDependency(
            id="rust-native",
            capability="hash_artifacts",
            tier="floor",
            weight=100.0,
            provider=lambda data: f"rust:{data}",
            readiness_probe=lambda: False,  # simulate unavailable binary
            fallback_id="uds-daemon",
        ),
        PrioritizedDependency(
            id="uds-daemon",
            capability="hash_artifacts",
            tier="standard",
            weight=80.0,
            provider=lambda data: (_ for _ in ()).throw(RuntimeError("socket closed")),
            readiness_probe=lambda: True,
            fallback_id="python-stdlib",
        ),
        PrioritizedDependency(
            id="python-stdlib",
            capability="hash_artifacts",
            tier="opportunistic",
            weight=10.0,
            provider=lambda data: f"stdlib:{data}",
            readiness_probe=lambda: True,
        ),
    ])

    res = resolver.resolve("hash_artifacts", "payload-1")
    assert res.selected_id == "python-stdlib"
    assert res.value == "stdlib:payload-1"
    assert [a["status"] for a in res.attempted] == ["unready", "failed", "selected"]


def test_stream_pipeline_modules_components_processes_and_receipt():
    # Define out-of-order stages across module, component, and process boundaries
    routing_engine = DecisionEngine([
        DecisionRule(id="fast-route", tier="floor", weight=10.0, outcome="fast", when=lambda c: c["payload"] >= 10),
        DecisionRule(id="slow-route", tier="standard", weight=5.0, outcome="slow", when=lambda c: True),
    ])

    stages = [
        StreamStage(
            id="proc-emit",
            kind="process",
            tier="standard",
            weight=10.0,
            depends_on=("comp-enrich",),
            transform=lambda env: {"value": env.payload, "route": env.decisions[-1]["outcome"]},
        ),
        StreamStage(
            id="comp-enrich",
            kind="component",
            tier="standard",
            weight=50.0,
            depends_on=("mod-parse", "mod-validate"),
            decision_engine=routing_engine,
            transform=lambda env: env.payload * 2,
        ),
        StreamStage(
            id="mod-validate",
            kind="module",
            tier="floor",
            weight=20.0,
            depends_on=("mod-parse",),
            transform=lambda env: env.payload if env.payload > 0 else (_ for _ in ()).throw(ValueError("negative")),
            fallback=lambda env, exc: 1,
        ),
        StreamStage(
            id="mod-parse",
            kind="module",
            tier="floor",
            weight=100.0,
            transform=lambda env: int(env.payload),
        ),
    ]

    pipeline = StreamPipeline("demo.stream", stages)
    assert [s.id for s in pipeline.ordered_stages] == [
        "mod-parse",
        "mod-validate",
        "comp-enrich",
        "proc-emit",
    ]

    # Verify lazy generator streaming one item at a time
    stream_iter = pipeline.stream(["5", "-3", "2"])
    first = next(stream_iter)
    assert first.payload == {"value": 10, "route": "slow"}
    assert pipeline.last_receipt is None  # stream not yet exhausted

    rest = list(stream_iter)
    assert [r.payload for r in rest] == [
        {"value": 2, "route": "slow"},   # -3 fell back to 1 -> *2 = 2
        {"value": 4, "route": "slow"},
    ]
    assert rest[0].trace[1]["status"] == "fallback"

    receipt = pipeline.last_receipt
    assert receipt is not None
    assert receipt.processed_count == 3
    assert receipt.digest.startswith("sha256:")
    assert receipt.stage_counts == {"mod-parse": 3, "mod-validate": 3, "comp-enrich": 3, "proc-emit": 3}


def test_stream_pipeline_rejects_cycles():
    s1 = StreamStage(id="a", kind="module", tier="floor", weight=1.0, depends_on=("b",), transform=lambda e: e.payload)
    s2 = StreamStage(id="b", kind="module", tier="floor", weight=1.0, depends_on=("a",), transform=lambda e: e.payload)
    with pytest.raises(ValueError, match="Cycle detected"):
        StreamPipeline("cyclic", [s1, s2])


def test_analyze_horizontal_complexity_detects_wide_branches_and_fanout(tmp_path: Path):
    code = "\n".join([
        "import os, sys, json, re, math, time, shutil, pathlib, hashlib, heapq, sqlite3, subprocess, tempfile",
        "def dispatch(x):",
        "    if x == 1: return 1",
        "    elif x == 2: return 2",
        "    elif x == 3: return 3",
        "    elif x == 4: return 4",
        "    elif x == 5: return 5",
        "    else: return 0",
    ])
    (tmp_path / "horizontal_hub.py").write_text(code, encoding="utf-8")
    report = analyze_horizontal_complexity(tmp_path, max_branch_arms=5, max_fan_out=12, max_file_lines=500)
    codes = {h["code"] for h in report["hotspots"]}
    assert "REUSE-015-FANOUT" in codes
    assert "REUSE-015-BRANCH-CHAIN" in codes


def test_stream_flow_schema_validates_declarative_document():
    root = Path(__file__).resolve().parent.parent
    schema = json.loads((root / "schemas" / "stream-flow.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    doc = {
        "schema": "wellmanifest.stream-flow/v1",
        "id": "demo.pipeline",
        "version": "1.0.0",
        "decisions": [
            {"id": "d1", "tier": "floor", "weight": 10, "when": "env.ready", "outcome": "fast"}
        ],
        "dependencies": [
            {"id": "dep.rust", "capability": "scanner", "tier": "floor", "weight": 100, "fallback_id": "dep.py"}
        ],
        "stages": [
            {"id": "s1", "kind": "module", "tier": "floor", "weight": 100, "depends_on": []},
            {"id": "s2", "kind": "component", "tier": "standard", "weight": 50, "depends_on": ["s1"]},
            {"id": "s3", "kind": "process", "tier": "opportunistic", "weight": 10, "depends_on": ["s2"]}
        ]
    }
    errors = list(Draft202012Validator(schema).iter_errors(doc))
    assert errors == []
