import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_standard_sources import audit


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()


def repository(root, files):
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.test")
    git(root, "config", "user.name", "Fixture")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / "wellmanifest/core"
    revision = repository(source, {"schema.json": '{"type":"string"}\n'})
    consumer = tmp_path / "wellmanifest/consumer"
    repository(consumer, {"schema.json": '{"type":"string"}\n'})
    ssot = tmp_path / "wellmanifest/ssot"
    # Minimal test contract isolates integrity checks; the real pinned SSOT
    # contract is exercised by the live catalogue command, without vendoring it.
    schema = '{"type":"object","required":["decisions"]}'
    schema_revision = repository(ssot, {"schema.json": schema})
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"path": "schema.json", "sourceRevision": schema_revision,
                               "sha256": hashlib.sha256(schema.encode()).hexdigest()}))
    decision = {"id": "core-schema", "kind": "vendored_copy",
                "canonical": {"ref": f"repo://wellmanifest/core@{revision}/schema.json",
                              "path": "wellmanifest/core/schema.json"},
                "trees": ["wellmanifest/consumer/schema.json"]}
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps({"decisions": [decision]}))
    return tmp_path, ssot, catalogue, lock


def edit_catalogue(fixture, edit):
    path = fixture[2]
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def test_pinned_copy_stays_valid_when_upstream_head_advances(fixture):
    root, _, _, _ = fixture
    source = root / "wellmanifest/core"
    (source / "schema.json").write_text('{"type":"number"}\n')
    git(source, "commit", "-qam", "new version")
    assert audit(*fixture)["passed"]


def test_consumer_drift_is_failure_with_observed_digests(fixture):
    (fixture[0] / "wellmanifest/consumer/schema.json").write_text("changed")
    result = audit(*fixture)
    assert not result["passed"]
    assert result["checks"][0]["status"] == "drift"
    assert result["checks"][0]["observedSha256"] != result["checks"][0]["expectedSha256"]


def test_changed_schema_pin_fails(fixture):
    (fixture[1] / "schema.json").write_text("{}")
    with pytest.raises(ValueError, match="immutable pin"):
        audit(*fixture)


def test_duplicate_consumer_assignment_fails(fixture):
    def duplicate(data):
        other = dict(data["decisions"][0], id="other")
        data["decisions"].append(other)
    edit_catalogue(fixture, duplicate)
    with pytest.raises(ValueError, match="assigned more than once"):
        audit(*fixture)


@pytest.mark.parametrize("relative", ["../outside", "/etc/passwd", "wellmanifest/../schema.json"])
def test_path_escape_fails(fixture, relative):
    edit_catalogue(fixture, lambda d: d["decisions"][0].update(trees=[relative]))
    with pytest.raises(ValueError, match="invalid relative path"):
        audit(*fixture)


def test_symlink_consumer_is_rejected(fixture):
    root = fixture[0]
    path = root / "wellmanifest/consumer/schema.json"
    path.unlink()
    path.symlink_to(root / "wellmanifest/core/schema.json")
    with pytest.raises(ValueError, match="symlink"):
        audit(*fixture)


def test_untracked_copy_is_rejected(fixture):
    root = fixture[0] / "wellmanifest/consumer"
    git(root, "rm", "--cached", "schema.json")
    with pytest.raises(subprocess.CalledProcessError):
        audit(*fixture)


def test_unknown_relationship_is_not_silently_excluded(fixture):
    edit_catalogue(fixture, lambda d: d["decisions"][0].update(kind="real_fork"))
    with pytest.raises(ValueError, match="parity profile accepts"):
        audit(*fixture)


def test_inconsistent_canonical_path_is_rejected(fixture):
    edit_catalogue(fixture, lambda d: d["decisions"][0]["canonical"].update(path="wellmanifest/other/schema.json"))
    with pytest.raises(ValueError, match="disagree"):
        audit(*fixture)
