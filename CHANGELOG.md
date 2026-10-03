# Changelog

All notable changes to the `wellmanifest/reuse` standard will be documented in this file.

## [0.1.0] - 2026-10-03

### Added
- Initial release of the Wellmanifest Reuse Standard (`wellmanifest/reuse@v1`).
- Canonical tool bindings in `standard/tool-bindings.json` mapping discovery (`semcod/search`), topology (`semcod/monag`), deduplication (`semcod/redup`), modularization (`wellmanifest/modularity`), planning (`planfile`), execution (`semcod/koru`), and docs/logs (`wellmanifest/docs`, `wellmanifest/logs`).
- Machine-readable reuse policy in `standard/reuse-policy.json` (`REUSE-001` through `REUSE-006`).
- Conformance validator script in `standard/conformance.py`.
- Automated planfile task generator in `scripts/generate_reuse_plan.py`.
- Unit tests for conformance and task generation.
- Pilot integration with `digitaltwin-run/dock2tauri`.
