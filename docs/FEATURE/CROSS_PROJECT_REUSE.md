# FEATURE: Cross-Project Discovery and Reuse Protocol

## Context
Across 240+ repositories in `~/github/*`, developers and autonomous agents frequently reimplement similar CLI arguments, file parsing routines, and packaging scripts instead of leveraging existing implementations. This feature formalizes the standardized query and extraction sequence.

## Scope & Decisions
1. **Zero-New-Code Heuristic**: When a prompt or ticket requests a new utility, query `subactor-search ask "<concept>"` first.
2. **Evaluation Matrix**:
   - Exact match found: add dependency or path reference.
   - Near-clone found (>75% similarity in `redup compare`): evaluate extracting to a shared module.
   - Novel requirement: implement within bounded scope and mark for future reuse.
3. **Continuous Modularization**: Shared code extracted from monorepo/individual projects lives under `packages/<name>` or a dedicated domain repo in `wellmanifest/*` or `semcod/*`.
4. **Standard Documentation**: Every reusable component must expose a Compact v2 specification under `docs/FEATURE/` (max 120 lines).

## Consequences
- Reduces redundant codebase volume by up to 30%.
- Unifies toolchain patterns across all agent frameworks (Antigravity, Koru, Subactor).
- Accelerates ticket completion since existing tested packages replace scratch implementations.
