"""Unit tests for wellmanifest/reuse conformance and schema validation."""

import json
from pathlib import Path

from standard.conformance import check_schema_files, run_conformance


def test_schema_validity():
    root = Path(__file__).resolve().parent.parent
    assert check_schema_files(root) is True


def test_conformance_on_self():
    root = Path(__file__).resolve().parent.parent
    res = run_conformance(root)
    # The standard itself should have docs
    assert res.checks is not None
    assert len(res.checks) >= 3


def test_policy_json_contents():
    root = Path(__file__).resolve().parent.parent
    policy_file = root / "standard" / "reuse-policy.json"
    with open(policy_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema"] == "wellmanifest.reuse-policy/v1"
    rule_codes = {r["code"] for r in data["rules"]}
    assert "REUSE-001" in rule_codes
    assert "REUSE-002" in rule_codes
    assert "REUSE-003" in rule_codes
    assert "REUSE-004" in rule_codes
    assert "REUSE-005" in rule_codes
    assert "REUSE-006" in rule_codes
