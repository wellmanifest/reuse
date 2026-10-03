"""Unit tests for planfile reuse task generation."""

import tempfile
from pathlib import Path

from scripts.generate_reuse_plan import create_reuse_tasks, update_planfile_sprint


def test_create_reuse_tasks():
    tmp_path = Path("/tmp/mock_project")
    tasks = create_reuse_tasks(tmp_path, topic="desktop")
    assert len(tasks) == 3
    
    ids = [t["id"] for t in tasks]
    assert all("reuse_" in i for i in ids)
    
    tiers = {t["tier"] for t in tasks}
    assert "reuse" in tiers
    assert "refactor" in tiers
    assert "hygiene" in tiers

    for t in tasks:
        assert "koru-autonomous" in t["labels"]
        assert "source" in t
        assert t["source"] == "wellmanifest/reuse"


def test_update_planfile_sprint():
    with tempfile.TemporaryDirectory() as td:
        sprint_file = Path(td) / "current.yaml"
        mock_tasks = [
            {
                "id": "t1",
                "title": "Task 1",
                "tier": "reuse",
                "labels": ["reuse"],
                "status": "todo"
            }
        ]
        added = update_planfile_sprint(sprint_file, mock_tasks)
        assert added == 1
        assert sprint_file.exists()
        
        # Test idempotence (no duplicates)
        added_again = update_planfile_sprint(sprint_file, mock_tasks)
        assert added_again == 0
