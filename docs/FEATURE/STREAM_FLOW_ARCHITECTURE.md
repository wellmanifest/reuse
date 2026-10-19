# FEATURE: Structural Stream Flow, Decision Routing & Prioritized Dependencies

## Context
Horizontal complexity arises when orchestrator modules accumulate wide `if/elif` trees (`>= 5` branches), excessive peer imports (`> 12` modules in the same layer), and monolithic in-memory batch loops (`> 500` lines). This couples independent components horizontally and obscures priority and fallback semantics.

## Normative Rules (`REUSE-015` .. `REUSE-018`)
1. **`REUSE-015` (Horizontal Complexity & Peer Fan-Out Ceiling)**:
   - Max imperative `if/elif` chain length: `< 5` branches.
   - Max module import fan-out: `<= 12` top-level dependencies.
   - Max module length: `<= 500` lines (`<= 150` lines for thin facades per `REUSE-011`).
2. **`REUSE-016` (Declarative Decision Graph & Lexicographic Priority Routing)**:
   - Multi-branch decisions are modeled as `DecisionRule(id, tier, weight, outcome, when, satisfied_when)` evaluated in lexicographic `(tier_rank, -weight, id)` order (`floor` > `standard` > `opportunistic`, aligned with `wellmanifest/priority`).
3. **`REUSE-017` (Prioritized Dependency & Fallback Chain)**:
   - Runtime providers (e.g., native Rust extension -> UDS daemon -> cached projection -> stdlib fallback) are registered as `PrioritizedDependency(id, capability, tier, weight, provider, readiness_probe, fallback_id)` resolved via `DependencyResolver`.
4. **`REUSE-018` (Streaming Composition of Modules, Components & Processes)**:
   - Workflows across modules (`kind="module"`), components (`kind="component"`), and processes (`kind="process"`) execute as lazy generator streams (`StreamPipeline.stream(items)`) over immutable `StreamEnvelope` records, sorted by prioritized Kahn topological sort (`depends_on` + lexicographic priority) and producing a SHA-256 `StreamReceipt`.

## Reference Implementation
- Module: [`standard/stream_flow.py`](../../standard/stream_flow.py)
- Schema: [`schemas/stream-flow.schema.json`](../../schemas/stream-flow.schema.json)
- Audit CLI: `python3 -m standard.stream_flow --project <repo_dir> --json`
