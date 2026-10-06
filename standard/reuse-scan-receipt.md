# REUSE-002 scan receipt (`wellmanifest.reuse-scan-receipt/v1`)

Path: `.reuse/redup-receipt.json`. REUSE-002 passes only when the receipt is valid and current.

```json
{"schema": "wellmanifest.reuse-scan-receipt/v1",
 "tool": {"name": "redup", "version": "1.0"},
 "revision": "<40-hex git commit scanned>",
 "scanned": [{"path": "src/mod.py", "sha256": "<64-hex>"}],
 "findings": {"clone_groups": 0, "unmitigated": 0}}
```

Status: `verified` | `unverified` (no receipt / git unobservable) | `invalid` (schema) | `stale` (file bytes changed, file missing, or revision not an ancestor of HEAD) | `failed` (`unmitigated` > 0).

Only `verified` passes. The revision is an ancestor check (not equality) so committing the receipt does not invalidate it; per-file digests detect later edits. The producer is not authenticated (`producer_authenticated: false`); trust in the receipt author needs a separate mechanism.
