"""Tests for reuse_orchestrator.py (semcod/code2logic, autogrammar/code2schema, subactor/intent)."""

import json
from pathlib import Path
from scripts.reuse_orchestrator import (
    CodeLogicAnalyzer,
    CloneDetector,
    ContractGenerator,
    IntentTicketDispatcher,
    infer_workstream,
)


def test_infer_workstream():
    assert infer_workstream(["src/app.py", "tests/test_app.py"]) == "application"
    assert infer_workstream(["pyproject.toml", "src/core.py"]) == "integration"
    assert infer_workstream([".governance/policy.json", "standards/check.py"]) == "governance"


def test_code_logic_analyzer(tmp_path):
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        "class Calculator:\n"
        "    '''Simple calculator.'''\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n\n"
        "def helper():\n"
        "    '''Helper function.'''\n"
        "    pass\n"
    )
    analyzer = CodeLogicAnalyzer(tmp_path)
    profile = analyzer.profile_project()
    assert profile["project"] == tmp_path.name
    assert len(profile["modules"]) == 1

    mod = profile["modules"][0]
    assert mod["file"] == "sample.py"
    assert len(mod["classes"]) == 1
    assert mod["classes"][0]["name"] == "Calculator"
    assert mod["classes"][0]["methods"] == ["add"]
    assert len(mod["functions"]) == 1
    assert mod["functions"][0]["name"] == "helper"


def test_contract_generator():
    profile = {
        "file": "test_module.py",
        "classes": [
            {"name": "AuthPayload", "docstring": "Authentication model", "methods": ["verify"]},
        ],
    }
    schema = ContractGenerator.generate_json_schema_from_pydantic_or_ast(profile)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "AuthPayload" in schema["definitions"]
    assert schema["definitions"]["AuthPayload"]["title"] == "AuthPayload"

    scenario = ContractGenerator.generate_testql_scenario("auth", ["verify", "login"])
    assert "target: auth" in scenario
    assert "assert: result is not None" in scenario


def test_intent_ticket_dispatcher(tmp_path):
    # Test next ticket id inference
    assert IntentTicketDispatcher.find_next_ticket_id(tmp_path) == "ticket-001"
    (tmp_path / "project" / "ticket-005").mkdir(parents=True)
    assert IntentTicketDispatcher.find_next_ticket_id(tmp_path) == "ticket-006"

    ticket_dir = IntentTicketDispatcher.write_ticket_files(
        target_repo=tmp_path,
        ticket_id="ticket-099",
        intent_data=IntentTicketDispatcher.create_reuse_intent(
            ticket_id="ticket-099",
            summary="Deduplicate twin auth logic",
            target_repo=tmp_path,
            allowed_paths=["src/twin.py", "tests/test_twin.py"],
        ),
    )
    assert ticket_dir.is_dir()
    intent_file = ticket_dir / "intent.json"
    assert intent_file.is_file()
    data = json.loads(intent_file.read_text())
    assert data["schema"] == "new-project.intent/v3"
    assert data["ticket"] == "ticket-099"
    assert data["workstream"] == "application"

    readme_file = ticket_dir / "README.md"
    assert readme_file.is_file()
    readme_text = readme_file.read_text()
    assert "- **Status**: IN_PROGRESS" in readme_text
    assert "- **Workflow state**: EDIT" in readme_text
