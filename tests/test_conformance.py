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
