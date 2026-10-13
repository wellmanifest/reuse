from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from standard.conformance import (
    RECEIPT_PATH,
    RECEIPT_SCHEMA,
    evaluate_scan_receipt,
    run_conformance,
)
from scripts.record_scan_receipt import (
    check_mitigation_in_planfile,
    get_git_head,
    record_scan_receipt,
)


def _init_git_repo(path: Path) -> str:
    """Initialize a git repo with an initial commit and return HEAD SHA."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test Agent"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "agent@example.com"], check=True)
    (path / "file1.py").write_text("def hello():\n    return 'world'\n")
    (path / "file2.py").write_text("def calc(a, b):\n    return a + b\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True)
    res = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return res.stdout.strip()


def test_get_git_head(tmp_path: Path):
    sha = _init_git_repo(tmp_path)
    assert get_git_head(tmp_path) == sha


def test_record_scan_receipt_generates_verified_receipt(tmp_path: Path):
    sha = _init_git_repo(tmp_path)
    data, verdict = record_scan_receipt(tmp_path)

    receipt_file = tmp_path / RECEIPT_PATH
    assert receipt_file.is_file()
    assert verdict["passed"] is True
    assert verdict["status"] == "verified"
    assert data["schema"] == RECEIPT_SCHEMA
    assert data["revision"] == sha
    assert len(data["scanned"]) >= 2
    assert data["findings"]["unmitigated"] == 0

    # Ensure evaluate_scan_receipt directly from standard also verifies it
    direct_verdict = evaluate_scan_receipt(tmp_path)
    assert direct_verdict["passed"] is True
    assert direct_verdict["status"] == "verified"


def test_record_scan_receipt_detects_planfile_mitigation(tmp_path: Path):
    _init_git_repo(tmp_path)
    sprints_dir = tmp_path / ".planfile" / "sprints"
    sprints_dir.mkdir(parents=True)
    (sprints_dir / "current.yaml").write_text(
        "sprint:\n"
        "  id: S01\n"
        "  tickets:\n"
        "    refactor_redup_clones:\n"
        "      status: in_progress\n"
    )
    assert check_mitigation_in_planfile(tmp_path) is True


def test_cli_execution_exits_zero(tmp_path: Path):
    _init_git_repo(tmp_path)
    script = Path(__file__).resolve().parent.parent / "scripts" / "record_scan_receipt.py"
    res = subprocess.run(
        [sys.executable, str(script), "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    out = json.loads(res.stdout)
    assert out["verdict"]["passed"] is True
    assert out["verdict"]["status"] == "verified"


def test_fleet_reuse_audit_record_receipt(tmp_path: Path):
    org_dir = tmp_path / "wellmanifest"
    repo_dir = org_dir / "sample-project"
    repo_dir.mkdir(parents=True)
    _init_git_repo(repo_dir)

    script = Path(__file__).resolve().parent.parent / "scripts" / "fleet_reuse_audit.py"
    res = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--orgs", "wellmanifest", "--record-receipt", "--json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert (repo_dir / RECEIPT_PATH).is_file()



def test_clone_groups_without_plan_are_unmitigated(tmp_path: Path, monkeypatch):
    import scripts.record_scan_receipt as recorder

    _init_git_repo(tmp_path)
    scanned = [{"path": "file1.py", "sha256": hashlib.sha256((tmp_path / "file1.py").read_bytes()).hexdigest()}]
    monkeypatch.setattr(recorder, "scan_with_redup", lambda *a, **k: ("0.4.48", scanned, 2))

    data, verdict = record_scan_receipt(tmp_path)

    assert data["findings"] == {"clone_groups": 2, "unmitigated": 2}
    assert verdict["status"] == "failed"


def test_missing_redup_writes_no_receipt(tmp_path: Path, monkeypatch):
    import builtins

    import scripts.record_scan_receipt as recorder

    _init_git_repo(tmp_path)
    real_import = builtins.__import__

    def no_redup(name, *args, **kwargs):
        if name == "redup" or name.startswith("redup."):
            raise ImportError("redup not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_redup)

    with pytest.raises(recorder.RedupUnavailable):
        record_scan_receipt(tmp_path)
    assert not (tmp_path / RECEIPT_PATH).exists()
