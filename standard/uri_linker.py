"""Cross-Language URI Process Linker & Prioritized Dockuri Resolver (REUSE-019 / URP-012)."""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from standard.stream_flow import DependencyResolver, PrioritizedDependency

VERSION = "0.5.0"
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")
_LOCAL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def validate_uri_address(address: str) -> Tuple[str, Dict[str, Any]]:
    """Validate `<scheme>://<authority>/<path>[?query]` and return `(canonical_uri, query_params)`."""
    raw = (address or "").strip()
    if not raw or any(c.isspace() or ord(c) < 32 for c in raw):
        raise ValueError(f"Invalid URI address: {address!r}")
    parts = urlsplit(raw)
    if (
        not (parts.scheme and _SCHEME_RE.match(parts.scheme) and parts.hostname and parts.path and parts.path != "/")
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise ValueError(f"Invalid URI address (expected <scheme>://<authority>/<path>): {address!r}")
    query_params: Dict[str, Any] = dict(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), query_params


def normalize_jsonl_records(payload: Any, query_params: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], bool]:
    """Normalize None, dict, list of dicts/JSON strings, or JSON/JSONL string into records + batch flag."""
    base = dict(query_params or {})
    if payload is None:
        return [dict(base)], False
    if isinstance(payload, dict):
        return [{**base, **payload}], False
    if isinstance(payload, (list, tuple)):
        if not payload:
            raise ValueError("JSONL payload sequence must not be empty")
        records: List[Dict[str, Any]] = []
        for item in payload:
            parsed = json.loads(item) if isinstance(item, str) else item
            if not isinstance(parsed, dict):
                raise ValueError("Each JSONL item must be a JSON object")
            records.append({**base, **parsed})
        return records, True
    if isinstance(payload, str):
        lines = [ln.strip() for ln in payload.splitlines() if ln.strip()]
        if not lines:
            raise ValueError("JSON/JSONL string payload must not be empty")
        records = []
        for ln in lines:
            parsed = json.loads(ln)
            if not isinstance(parsed, dict):
                raise ValueError("Each JSONL line must decode to a JSON object")
            records.append({**base, **parsed})
        return records, (len(records) > 1 or "\n" in payload.strip())
    raise TypeError(f"Unsupported URI payload type: {type(payload)!r}")


def register_local_uri_handler(address: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    """Register an in-process URI handler for testing or local floor resolution."""
    clean_uri, _ = validate_uri_address(address)
    _LOCAL_HANDLERS[clean_uri] = handler


def _load_dockuri_uri_module() -> Optional[Any]:
    try:
        return importlib.import_module("dockuri_uri")
    except ImportError:
        for cand in (
            Path.home() / "github" / "paxlet-com" / "dockuri" / "python",
            Path.home() / "github" / "dockuri" / "dockuri" / "python",
        ):
            if (cand / "dockuri_uri.py").is_file():
                if str(cand) not in sys.path:
                    sys.path.insert(0, str(cand))
                try:
                    return importlib.import_module("dockuri_uri")
                except ImportError:
                    continue
        return None


def _resolve_uri_cli_command() -> Optional[List[str]]:
    local_bin = Path.home() / ".local" / "bin" / "uri"
    if local_bin.is_file() and os.access(local_bin, os.X_OK):
        return [str(local_bin)]
    which_uri = shutil.which("uri")
    if which_uri:
        return [which_uri]
    return [sys.executable, "-m", "dockuri_uri"] if _load_dockuri_uri_module() is not None else None


def _floor_in_process_invoke(address: str, payload: Any = None, **kwargs: Any) -> Any:
    clean_uri, query_params = validate_uri_address(address)
    records, is_batch = normalize_jsonl_records(payload, query_params)
    if clean_uri in _LOCAL_HANDLERS:
        handler = _LOCAL_HANDLERS[clean_uri]
        results = [handler({**rec, **kwargs}) for rec in records]
        return results if is_batch else results[0]
    mod = _load_dockuri_uri_module()
    if mod is None:
        raise RuntimeError("dockuri_uri module is not available in-process")
    return mod.uri(address, payload, **kwargs)


def _standard_cli_invoke(address: str, payload: Any = None, **kwargs: Any) -> Any:
    clean_uri, query_params = validate_uri_address(address)
    records, is_batch = normalize_jsonl_records(payload, query_params)
    cmd_prefix = _resolve_uri_cli_command()
    if not cmd_prefix:
        raise RuntimeError("uri CLI executable is not available")
    stdin_text = "\n".join(json.dumps({**rec, **kwargs}, sort_keys=True) for rec in records) + "\n"
    proc = subprocess.run([*cmd_prefix, clean_uri, "-"], input=stdin_text, capture_output=True, text=True, timeout=30, check=False)
    out_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if proc.returncode != 0 and not out_lines:
        raise RuntimeError(f"uri CLI failed ({proc.returncode}): {proc.stderr.strip()}")
    parsed = [json.loads(ln) for ln in out_lines]
    if not parsed:
        raise RuntimeError("uri CLI returned empty output")
    return parsed if is_batch else parsed[0]


def build_uri_resolver(
    *,
    floor_provider: Optional[Callable[..., Any]] = None,
    floor_ready: Optional[Callable[[], bool]] = None,
    standard_provider: Optional[Callable[..., Any]] = None,
    standard_ready: Optional[Callable[[], bool]] = None,
) -> DependencyResolver:
    """Create the prioritized DependencyResolver (`floor` in-process -> `standard` CLI JSONL)."""
    resolver = DependencyResolver()
    resolver.register(
        PrioritizedDependency(
            id="floor:dockuri_in_process",
            capability="uri.invoke",
            tier="floor",
            weight=100.0,
            provider=floor_provider or _floor_in_process_invoke,
            readiness_probe=floor_ready or (lambda: bool(_LOCAL_HANDLERS) or _load_dockuri_uri_module() is not None),
            fallback_id="standard:uri_cli_jsonl",
        )
    )
    resolver.register(
        PrioritizedDependency(
            id="standard:uri_cli_jsonl",
            capability="uri.invoke",
            tier="standard",
            weight=50.0,
            provider=standard_provider or _standard_cli_invoke,
            readiness_probe=standard_ready or (lambda: _resolve_uri_cli_command() is not None),
        )
    )
    return resolver


DEFAULT_URI_RESOLVER = build_uri_resolver()


def uri(address: str, payload: Any = None, *, resolver: Optional[DependencyResolver] = None, **kwargs: Any) -> Any:
    """Invoke a URI process (`<scheme>://<authority>/<path>`) via prioritized DependencyResolver (REUSE-019)."""
    validate_uri_address(address)
    return (resolver or DEFAULT_URI_RESOLVER).resolve("uri.invoke", address, payload, **kwargs).value


def uri_jsonl(address: str, lines: Iterable[Any], *, resolver: Optional[DependencyResolver] = None, **kwargs: Any) -> List[Dict[str, Any]]:
    """Stream an iterable of JSONL strings or dicts into a URI process and return list of results."""
    res = uri(address, list(lines), resolver=resolver, **kwargs)
    return res if isinstance(res, list) else [res]


_LANG_TEMPLATES: Dict[str, Callable[[str, str], str]] = {
    "python": lambda target, djson: (
        f"from standard.uri_linker import uri\n\n_DEFAULTS = {djson}\n\n"
        "def invoke(payload=None, **kwargs):\n"
        "    body = {**_DEFAULTS, **(payload or {})} if isinstance(payload, dict) or payload is None else payload\n"
        f"    return uri({target!r}, body, **kwargs)\n"
    ),
    "bash": lambda target, djson: f'#!/usr/bin/env bash\nset -euo pipefail\nPAYLOAD="${{1:-{djson}}}"\nuri "{target}" "$PAYLOAD"\n',
    "javascript": lambda target, djson: (
        f'import {{ uri }} from "dockuri-uri";\n\nconst DEFAULTS = {djson};\n\n'
        "export async function invoke(payload = {}) {\n"
        "  const body = typeof payload === 'string' ? payload : { ...DEFAULTS, ...payload };\n"
        f'  return await uri("{target}", body);\n}}\n'
    ),
    "typescript": lambda target, djson: (
        f'import {{ uri }} from "dockuri-uri";\n\nconst DEFAULTS: Record<string, unknown> = {djson};\n\n'
        "export async function invoke(payload: Record<string, unknown> | string = {}): Promise<unknown> {\n"
        "  const body = typeof payload === 'string' ? payload : { ...DEFAULTS, ...payload };\n"
        f'  return await uri("{target}", body);\n}}\n'
    ),
    "rust": lambda target, djson: (
        "use dockuri_uri::uri;\nuse serde_json::Value;\n\n"
        "pub fn invoke(payload: Option<&str>) -> Result<Value, String> {\n"
        f'    let body = payload.unwrap_or("{djson.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}");\n'
        f'    uri("{target}", body)\n}}\n'
    ),
}
_LANG_ALIASES: Dict[str, str] = {"py": "python", "sh": "bash", "shell": "bash", "js": "javascript", "mjs": "javascript", "ts": "typescript", "rs": "rust"}


def render_polyglot_link(target_uri: str, lang: str = "python", defaults: Optional[Dict[str, Any]] = None) -> str:
    """Render a zero-duplication polyglot wrapper for Python, Bash, JS, TS, or Rust (REUSE-019 / URP-012)."""
    _, query_params = validate_uri_address(target_uri)
    key = (lang or "").strip().lower()
    renderer = _LANG_TEMPLATES.get(_LANG_ALIASES.get(key, key))
    if renderer is None:
        raise ValueError(f"Unsupported polyglot language: {lang!r}")
    defaults_json = json.dumps({**query_params, **(defaults or {})}, sort_keys=True, separators=(",", ":"))
    return renderer(target_uri, defaults_json)
