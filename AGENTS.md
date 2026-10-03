# Agent Contract for wellmanifest/reuse

Standard guidelines for AI coding agents (Antigravity, Koru, Subactor, Devin) maintaining this standard:

1. **Standard Authority**: `wellmanifest/reuse` defines cross-repository reuse governance. All changes to policy rules or tool bindings must remain backwards-compatible with existing `semcod/*` and `wellmanifest/*` tooling.
2. **Deterministic Schemas**: Any modification to `standard/reuse-policy.json` or `standard/tool-bindings.json` must be validated via `python3 standard/conformance.py --check-schema`.
3. **No Direct Commits on Main**: Work in isolated worktrees under `.worktrees/ticket-NNN--description` following Wellmanifest Worktrees v5.
4. **Prymat Zielonych Testów**: Autonomous merge authorized when all tests in `tests/` pass with exit code 0.
