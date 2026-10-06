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


# --- stable identity, atomic merge, malformed-input preservation, concurrency ---
import multiprocessing

import pytest
import yaml

from scripts.generate_reuse_plan import PlanfileError, main


def test_ids_are_stable_across_runs_and_distinct_per_project_topic(tmp_path):
    a = create_reuse_plan_data(tmp_path / "proj", topic="x")
    b = create_reuse_plan_data(tmp_path / "proj", topic="x")
    assert [t["id"] for t in a[0]] == [t["id"] for t in b[0]]
    assert list(a[1]) == list(b[1])
    other = create_reuse_plan_data(tmp_path / "proj", topic="y")
    assert {t["id"] for t in other[0]}.isdisjoint({t["id"] for t in a[0]})


def test_repeat_runs_do_not_duplicate_tasks_or_tickets(tmp_path):
    sprint = tmp_path / "current.yaml"
    for _ in range(3):
        tasks, tickets = create_reuse_plan_data(tmp_path / "proj", topic="x")
        update_planfile_sprint(sprint, tasks, tickets)
    data = yaml.safe_load(sprint.read_text())
    assert len(data["tasks"]) == 3
    assert len(data["sprint"]["tickets"]) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_tickets_and_unrelated_content_are_preserved(tmp_path):
    sprint = tmp_path / "current.yaml"
    sprint.write_text(yaml.safe_dump({"sprint": {"id": "s9", "tickets": {"PLF-1": {"id": "PLF-1", "status": "review"}}},
                                      "tasks": [{"id": "keep", "title": "Keep"}], "extra": {"k": 1}}))
    tasks, tickets = create_reuse_plan_data(tmp_path / "proj", topic="x")
    update_planfile_sprint(sprint, tasks, tickets)
    data = yaml.safe_load(sprint.read_text())
    assert data["sprint"]["id"] == "s9"
    assert data["sprint"]["tickets"]["PLF-1"] == {"id": "PLF-1", "status": "review"}
    assert data["extra"] == {"k": 1} and data["tasks"][0]["id"] == "keep"


@pytest.mark.parametrize("content", ["{broken: [", "- just\n- a list\n", "sprint: 5\n", "sprint: {tickets: []}\n",
                                     "sprint: {tickets: {}}\ntasks: nope\n"])
def test_malformed_existing_state_is_preserved_and_aborts(tmp_path, content):
    sprint = tmp_path / "current.yaml"
    sprint.write_text(content)
    tasks, tickets = create_reuse_plan_data(tmp_path / "proj", topic="x")
    with pytest.raises(PlanfileError):
        update_planfile_sprint(sprint, tasks, tickets)
    assert sprint.read_text() == content


def test_main_exits_nonzero_and_leaves_malformed_file_untouched(tmp_path):
    project = tmp_path / "proj"
    (project / ".planfile" / "sprints").mkdir(parents=True)
    sprint = project / ".planfile" / "sprints" / "current.yaml"
    sprint.write_text("{broken: [")
    import sys
    from unittest import mock
    with mock.patch.object(sys, "argv", ["gen", "--project", str(project)]):
        assert main() == 1
    assert sprint.read_text() == "{broken: ["


def _worker(args):
    sprint, project = args
    tasks, tickets = create_reuse_plan_data(Path(project), topic="x")
    update_planfile_sprint(Path(sprint), tasks, tickets)


def test_concurrent_runs_do_not_duplicate(tmp_path):
    sprint = tmp_path / "current.yaml"
    with multiprocessing.get_context("spawn").Pool(6) as pool:
        pool.map(_worker, [(str(sprint), str(tmp_path / "proj"))] * 12)
    data = yaml.safe_load(sprint.read_text())
    assert len(data["tasks"]) == 3 and len(data["sprint"]["tickets"]) == 3
