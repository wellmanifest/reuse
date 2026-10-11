#!/usr/bin/env python3
"""Read-only parity checks using the shared, pinned SSOT decision contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError, SchemaError

ROOT = Path(__file__).resolve().parent.parent
SOURCE = re.compile(r"repo://([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@([0-9a-f]{40})/(.+)")


def bounded_path(root: Path, relative: str) -> Path:
    """Reject traversal and symlinks before reading any referenced artifact."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in (".", "..") for p in parts) or "\\" in relative:
        raise ValueError(f"invalid relative path: {relative}")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink in artifact path: {relative}")
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True, timeout=30).strip()


def audit(workspace: Path, ssot_root: Path, catalogue: Path = ROOT / "standard/standard-sources.ssot.json",
          lock_path: Path = ROOT / "standard/ssot.lock.json") -> dict:
    workspace = workspace.resolve(strict=True)
    lock = json.loads(lock_path.read_text())
    schema_bytes = bounded_path(ssot_root, lock["path"]).read_bytes()
    if hashlib.sha256(schema_bytes).hexdigest() != lock["sha256"]:
        raise ValueError("SSOT schema differs from its immutable pin")
    pinned_bytes = subprocess.check_output(["git", "-C", str(ssot_root), "show",
                                            f'{lock["sourceRevision"]}:{lock["path"]}'],
                                           stderr=subprocess.PIPE, timeout=30)
    if pinned_bytes != schema_bytes:
        raise ValueError("SSOT schema revision differs from its content pin")
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    document = json.loads(catalogue.read_text())
    Draft202012Validator(schema).validate(document)
    ids = [d["id"] for d in document["decisions"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("catalogue must contain unique decisions")
    checked, seen = [], set()
    for decision in document["decisions"]:
        if decision["kind"] not in ("generated_mirror", "vendored_copy"):
            raise ValueError("parity profile accepts only generated_mirror and vendored_copy")
        match = SOURCE.fullmatch(decision["canonical"]["ref"])
        if match is None:
            raise ValueError("canonical source must bind a repository, full Git SHA and path")
        repository, revision, source_path = match.groups()
        source_root = bounded_path(workspace, repository)
        bounded_path(source_root, source_path)
        if decision["canonical"].get("path") != f"{repository}/{source_path}":
            raise ValueError("canonical path and pinned source reference disagree")
        source = subprocess.check_output(["git", "-C", str(source_root), "show", f"{revision}:{source_path}"],
                                         stderr=subprocess.PIPE, timeout=30)
        if not decision["trees"]:
            raise ValueError("decision must identify at least one consumer")
        for relative in decision["trees"]:
            if relative in seen:
                raise ValueError(f"consumer assigned more than once: {relative}")
            seen.add(relative)
            path = bounded_path(workspace, relative)
            parts = Path(relative).parts
            if len(parts) < 3:
                raise ValueError("consumer must be a repository-relative file")
            consumer_root = bounded_path(workspace, str(Path(*parts[:2])))
            tracked = git(consumer_root, "ls-files", "--error-unmatch", "--", str(Path(*parts[2:])))
            if not tracked:
                raise ValueError(f"untracked consumer: {relative}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = hashlib.sha256(source).hexdigest()
            checked.append({"decision": decision["id"], "kind": decision["kind"],
                            "consumer": relative, "consumerRevision": git(consumer_root, "rev-parse", "HEAD"),
                            "source": decision["canonical"]["ref"], "expectedSha256": expected,
                            "observedSha256": digest, "status": "verified" if digest == expected else "drift"})
    return {"schema": "wellmanifest.reuse/standard-source-report/v1", "readOnly": True,
            "authority": "none", "catalogueSha256": hashlib.sha256(catalogue.read_bytes()).hexdigest(),
            "schemaSha256": lock["sha256"], "checkedCopies": len(checked),
            "passed": bool(checked) and all(c["status"] == "verified" for c in checked), "checks": checked}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--ssot-root", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, default=ROOT / "standard/standard-sources.ssot.json")
    parser.add_argument("--lock", type=Path, default=ROOT / "standard/ssot.lock.json")
    args = parser.parse_args()
    try:
        result = audit(args.workspace, args.ssot_root, args.catalogue, args.lock)
    except (OSError, ValueError, KeyError, ValidationError, SchemaError, subprocess.SubprocessError) as exc:
        print(json.dumps({"passed": False, "authority": "none", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
