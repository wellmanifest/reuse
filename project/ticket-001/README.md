# Ticket 001: Configurable sprints directory and canonical ticket intent carriers in REUSE-004

- **ID**: ticket-001
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-01

## Scope
1. Replace the hardcoded `.planfile/sprints` assumption in `standard/conformance.py` with configurable sprint directory resolution (`--sprints-dir`, `.planfile/config.yaml` `sprints_dir`/`paths.sprints`, `planfile/sprints`) confined within the project root, plus canonical `project/ticket-*/intent.json` orchestration carrier detection.
2. Add unit tests in `tests/test_conformance.py`.
