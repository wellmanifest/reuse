# Changelog

All notable changes to the `wellmanifest/reuse` standard will be documented in this file.

## [Unreleased]

### Fixed
- REUSE-006B accepts a nonempty `docs/**/TROUBLESHOOTING.md` in any
  wellmanifest/docs kind folder, so adopters can satisfy both standards (#9).
- `record_scan_receipt.py` counts every clone group without a plan or explicit
  mitigation as unmitigated (no undocumented 2-group grace), and fails without
  writing a receipt when semcod/redup cannot run instead of recording a
  zero-clone `verified` receipt (#11).

## [0.2.0] - 2026-10-12

### Added
- Expanded reuse policy with `REUSE-007` (semcod/code2logic AST & logic profiling), `REUSE-008` (autogrammar/code2schema canonical DSL contract generation), `REUSE-009` (subactor/intent sequential intent ticket dispatching), and `REUSE-010` (autogrammar/testql behavior parity verification).
- Added tool bindings for `semcod/code2logic`, `autogrammar/code2schema`, `subactor/intent-contract-dsl-runtime`, and `autogrammar/testql` in `standard/tool-bindings.json`.
- Implemented `scripts/reuse_orchestrator.py` integrating AST analysis, clone detection, contract generation, and intent ticket dispatch.
- Added comprehensive unit tests in `tests/test_reuse_orchestrator.py`.

## [0.1.1] - 2026-10-11

- Standard-source checks now validate the pinned canonical SSOT semantic rules, fail closed on missing/tampered validator code, and declare parity gates for vendored copies.

- Shared source routing distinguishes verified standard projections from duplication debt — [profile](docs/information/standard-source-reuse.md).

## [0.1.0] - 2026-10-03

### Added
- Initial release of the Wellmanifest Reuse Standard (`wellmanifest/reuse@v1`).
- Canonical tool bindings in `standard/tool-bindings.json` mapping discovery (`semcod/search`), topology (`semcod/monag`), deduplication (`semcod/redup`), modularization (`wellmanifest/modularity`), planning (`planfile`), execution (`semcod/koru`), and docs/logs (`wellmanifest/docs`, `wellmanifest/logs`).
- Machine-readable reuse policy in `standard/reuse-policy.json` (`REUSE-001` through `REUSE-006`).
- Conformance validator script in `standard/conformance.py`.
- Automated planfile task generator in `scripts/generate_reuse_plan.py`.
- Unit tests for conformance and task generation.
- Pilot integration with `digitaltwin-run/dock2tauri`.
