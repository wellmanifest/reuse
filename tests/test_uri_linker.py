"""Unit tests for REUSE-019 cross-language URI process linking & prioritized resolver."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from standard.uri_linker import (
    VERSION,
    build_uri_resolver,
    register_local_uri_handler,
    render_polyglot_link,
    uri,
    uri_jsonl,
    validate_uri_address,
)


def test_reuse_019_policy_and_version_0_5_0():
    root = Path(__file__).resolve().parent.parent
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.5.0"
    assert VERSION == "0.5.0"
    policy = json.loads((root / "standard" / "reuse-policy.json").read_text(encoding="utf-8"))
    assert policy["version"] == "0.5.0"
    by_code = {r["code"]: r for r in policy["rules"]}
    assert "REUSE-019" in by_code
    r19 = by_code["REUSE-019"]
    assert r19["name"] == "Cross-Language URI Process Linking & Dockuri Centralization"
    assert "proc://system/process/manage/v1" in r19["statement"]


def test_uri_and_uri_jsonl_via_local_handler_and_prioritized_fallback():
    register_local_uri_handler(
        "proc://test/reuse019/echo",
        lambda params: {"status": "ok", "uri": "proc://test/reuse019/echo", "params": params},
    )
    single = uri("proc://test/reuse019/echo?env=prod", {"count": 3})
    assert single["status"] == "ok"
    assert single["params"] == {"env": "prod", "count": "3" if False else 3}

    stream_out = uri_jsonl(
        "proc://test/reuse019/echo",
        ['{"seq": 1}', {"seq": 2}],
    )
    assert len(stream_out) == 2
    assert [item["params"]["seq"] for item in stream_out] == [1, 2]

    # Verify fallback from floor to standard CLI tier when floor is unready
    resolver = build_uri_resolver(
        floor_ready=lambda: False,
        standard_ready=lambda: True,
        standard_provider=lambda address, payload=None, **kw: {
            "status": "ok",
            "tier": "standard",
            "address": address,
            "payload": payload,
        },
    )
    res = resolver.resolve("uri.invoke", "proc://system/process/manage/v1", {"action": "snippet"})
    assert res.selected_id == "standard:uri_cli_jsonl"
    assert res.tier == "standard"
    assert res.value["tier"] == "standard"


def test_validate_uri_address_rejects_malformed_uris():
    clean, q = validate_uri_address("willman://operation/ast-horizontal-complexity/v1?max=5")
    assert clean == "willman://operation/ast-horizontal-complexity/v1"
    assert q == {"max": "5"}

    for bad in ("", "not-a-uri", "proc://host/", "https://user:pass@host/path", "proc://host/path#frag"):
        with pytest.raises(ValueError):
            validate_uri_address(bad)


@pytest.mark.parametrize(
    "lang,expected_marker",
    [
        ("python", "from standard.uri_linker import uri"),
        ("bash", 'uri "proc://system/process/manage/v1"'),
        ("javascript", 'import { uri } from "dockuri-uri";'),
        ("typescript", "Promise<unknown>"),
        ("rust", "use dockuri_uri::uri;"),
    ],
)
def test_render_polyglot_link_five_languages(lang: str, expected_marker: str):
    target = "proc://system/process/manage/v1"
    code = render_polyglot_link(target, lang=lang, defaults={"action": "relocate"})
    assert expected_marker in code
    assert target in code
    assert "relocate" in code


def test_render_polyglot_link_rejects_unknown_language():
    with pytest.raises(ValueError):
        render_polyglot_link("proc://system/process/manage/v1", lang="fortran")
