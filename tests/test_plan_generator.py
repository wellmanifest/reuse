"""Unit tests for planfile reuse task generation."""

import tempfile
from pathlib import Path

from scripts.generate_reuse_plan import create_reuse_plan_data, update_planfile_sprint


def test_create_reuse_tasks():
    tmp_path = Path("/tmp/mock_project")
    tasks, tickets = create_reuse_plan_data(tmp_path, topic="desktop")
    assert len(tasks) == 3
    assert len(tickets) == 3
    
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

    for tid, tdata in tickets.items():
        assert "REUSE-" in tid
        assert tdata["execution"]["state"] == "ready"
        assert tdata["executor"]["mode"] == "autonomous"


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
        mock_tickets = {
            "REUSE-T1": {
                "id": "REUSE-T1",
                "name": "Task 1",
                "status": "open"
            }
        }
        added = update_planfile_sprint(sprint_file, mock_tasks, mock_tickets)
        assert added == 1
        assert sprint_file.exists()
        
        # Test idempotence (no duplicates)
        added_again = update_planfile_sprint(sprint_file, mock_tasks, mock_tickets)
        assert added_again == 0
