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


def test_empty_structure_is_not_conformance(tmp_path):
    for directory in ('.planfile/sprints', 'docs', 'logs', 'errors'):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / 'README.md').write_text('# Project\n')
    result = run_conformance(tmp_path)
    checks = {check['code']: check for check in result.checks}
    assert result.passed is False
    assert all(not checks[code]['passed'] for code in ('REUSE-004', 'REUSE-006A', 'REUSE-006B', 'REUSE-002'))
    assert checks['REUSE-002']['details']['status'] == 'unverified'


def test_content_checks_do_not_claim_standard_enforcement(tmp_path):
    (tmp_path / '.planfile/sprints').mkdir(parents=True)
    (tmp_path / '.planfile/sprints/current.yaml').write_text('sprint:\n  id: sprint-001\n  tickets: {}\n')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/README.md').write_text('# Documentation\n')
    (tmp_path / 'errors').mkdir()
    (tmp_path / 'errors/E001.md').write_text('# E001\nRecover by retrying.\n')
    result = run_conformance(tmp_path)
    checks = {check['code']: check for check in result.checks}
    assert all(checks[code]['passed'] for code in ('REUSE-004', 'REUSE-006A', 'REUSE-006B'))
    assert result.passed is False  # duplication evidence is still absent
    assert checks['REUSE-006A']['details']['standard_enforcement_verified'] is False


def test_invalid_schema_rejected_under_optimized_python(tmp_path):
    import subprocess
    import sys
    (tmp_path / 'standard').mkdir()
    for name in ('reuse-policy.json', 'tool-bindings.json'):
        (tmp_path / 'standard' / name).write_text('{}')
    script = 'from pathlib import Path; from standard.conformance import check_schema_files; import sys; sys.exit(0 if not check_schema_files(Path(sys.argv[1])) else 1)'
    run = subprocess.run([sys.executable, '-O', '-c', script, str(tmp_path)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_malformed_nonempty_planfile_is_not_evidence(tmp_path):
    (tmp_path / '.planfile/sprints').mkdir(parents=True)
    (tmp_path / '.planfile/sprints/current.yaml').write_text('sprint: [broken')
    checks = {check['code']: check for check in run_conformance(tmp_path).checks}
    assert checks['REUSE-004']['passed'] is False


# --- REUSE-002 revision- and digest-bound scan receipts -------------------------
import hashlib
import subprocess

from standard.conformance import RECEIPT_PATH, RECEIPT_SCHEMA, evaluate_scan_receipt


def _repo(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "mod.py").write_text("print('x')\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return git, git("rev-parse", "HEAD")


def _receipt(tmp_path, rev, **overrides):
    revision = rev
    digest = hashlib.sha256((tmp_path / "mod.py").read_bytes()).hexdigest()
    value = {"schema": RECEIPT_SCHEMA, "tool": {"name": "redup", "version": "1.0"}, "revision": revision,
             "scanned": [{"path": "mod.py", "sha256": digest}],
             "findings": {"clone_groups": 0, "unmitigated": 0}}
    value.update(overrides)
    (tmp_path / RECEIPT_PATH).parent.mkdir(exist_ok=True)
    (tmp_path / RECEIPT_PATH).write_text(json.dumps(value))


def test_valid_receipt_verifies_but_does_not_authenticate_producer(tmp_path):
    _, rev = _repo(tmp_path)
    _receipt(tmp_path, rev)
    verdict = evaluate_scan_receipt(tmp_path)
    assert verdict["status"] == "verified" and verdict["passed"] is True
    assert verdict["producer_authenticated"] is False


def test_missing_receipt_is_unverified(tmp_path):
    _repo(tmp_path)
    assert evaluate_scan_receipt(tmp_path)["status"] == "unverified"


def test_scanned_file_changed_after_scan_is_stale(tmp_path):
    _, rev = _repo(tmp_path)
    _receipt(tmp_path, rev)
    (tmp_path / "mod.py").write_text("print('changed')\n")
    assert evaluate_scan_receipt(tmp_path)["status"] == "stale"


def test_unknown_or_unrelated_revision_is_stale(tmp_path):
    _repo(tmp_path)
    _receipt(tmp_path, "0" * 40)
    assert evaluate_scan_receipt(tmp_path)["status"] == "stale"


def test_unmitigated_clones_fail(tmp_path):
    _, rev = _repo(tmp_path)
    _receipt(tmp_path, rev, findings={"clone_groups": 2, "unmitigated": 1})
    verdict = evaluate_scan_receipt(tmp_path)
    assert verdict["status"] == "failed" and verdict["passed"] is False


def test_invalid_receipts_never_pass(tmp_path):
    _, rev = _repo(tmp_path)
    for bad in ({"schema": "other"}, {"revision": "abc"}, {"scanned": []}, {"tool": {}},
                {"findings": {"clone_groups": -1, "unmitigated": 0}},
                {"scanned": [{"path": "../outside", "sha256": "a" * 64}]},
                {"scanned": [{"path": "mod.py", "sha256": "nothex"}]}):
        _receipt(tmp_path, rev, **bad)  # overrides replace valid fields
        assert evaluate_scan_receipt(tmp_path)["passed"] is False, bad
    (tmp_path / RECEIPT_PATH).write_text("{not json")
    assert evaluate_scan_receipt(tmp_path)["status"] == "invalid"


def test_run_conformance_reuse_002_follows_receipt(tmp_path):
    _, rev = _repo(tmp_path)
    check = {c["code"]: c for c in run_conformance(tmp_path).checks}["REUSE-002"]
    assert check["passed"] is False
    _receipt(tmp_path, rev)
    check = {c["code"]: c for c in run_conformance(tmp_path).checks}["REUSE-002"]
    assert check["passed"] is True and check["details"]["status"] == "verified"


# --- JSON Schema validation with negative fixtures (also run under python -O) ----
import copy
import shutil

import pytest


def _standard_copy(tmp_path):
    root = Path(__file__).resolve().parent.parent
    (tmp_path / "standard").mkdir()
    for name in ("reuse-policy.json", "tool-bindings.json"):
        shutil.copy(root / "standard" / name, tmp_path / "standard" / name)
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    return tmp_path


def _mutate(tmp_path, filename, edit):
    path = tmp_path / "standard" / filename
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def test_schema_copy_baseline_is_valid(tmp_path):
    assert check_schema_files(_standard_copy(tmp_path)) is True


@pytest.mark.parametrize("filename,edit", [
    ("reuse-policy.json", lambda d: d["rules"].pop()),
    ("reuse-policy.json", lambda d: d["rules"][1].update(code=d["rules"][0]["code"])),
    ("reuse-policy.json", lambda d: d["rules"][0].update(severity="URGENT")),
    ("reuse-policy.json", lambda d: d["rules"][0].update(code="RULE-1")),
    ("reuse-policy.json", lambda d: d["rules"][1]["thresholds"].update(similarity_threshold=1.5)),
    ("reuse-policy.json", lambda d: d["rules"][1]["thresholds"].update(min_lines=0)),
    ("reuse-policy.json", lambda d: d["rules"][1]["thresholds"].pop("max_unmitigated_duplicate_groups")),
    ("reuse-policy.json", lambda d: d.update(schema="wrong")),
    ("reuse-policy.json", lambda d: d["rules"][0].pop("statement")),
    ("tool-bindings.json", lambda d: d["bindings"].pop()),
    ("tool-bindings.json", lambda d: d["bindings"][1].update(code=d["bindings"][0]["code"])),
    ("tool-bindings.json", lambda d: d["bindings"][0].pop("command")),
    ("tool-bindings.json", lambda d: d["bindings"][0].update(command="")),
    ("tool-bindings.json", lambda d: d.update(schema="wrong")),
])
def test_invalid_standard_files_are_rejected(tmp_path, filename, edit):
    root = _standard_copy(tmp_path)
    _mutate(root, filename, edit)
    assert check_schema_files(root) is False


def test_missing_or_corrupt_schema_inputs_are_rejected(tmp_path):
    root = _standard_copy(tmp_path)
    (root / "standard" / "tool-bindings.json").write_text("{broken")
    assert check_schema_files(root) is False
    shutil.rmtree(root / "schemas")
    assert check_schema_files(root) is False

