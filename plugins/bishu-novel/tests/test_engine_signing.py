from __future__ import annotations

import hashlib
import inspect
import json
import time

from ai_company_plugin_bishu_novel.backend.engine_signing import (
    SIGNATURE_PREFIX,
    build_canonical_query,
    build_canonical_string,
    compute_body_sha256,
    compute_signature,
    verify_signature,
)
from ai_company_plugin_bishu_novel.backend.nonce_store import InMemoryNonceStore


TEST_SECRET = "test-only-signing-key-" + ("x" * 48)  # pragma: allowlist secret


def _request() -> dict:
    body = json.dumps(
        {"human_intent": "继续", "target_word_count": "3000-4000"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    values = {
        "method": "POST",
        "path": "/api/v1/novel/books/book-demo/chapters/3/generate",
        "query_string": "preview=1&lang=zh",
        "body_bytes": body,
        "timestamp": "1718409600",
        "nonce": "test-nonce-0000000000000000000000",
        "kid": "test-key",
        "actor_ref": "test-actor",
        "request_id": "test-request",
        "idempotency_key": "test-task",
    }
    canonical = build_canonical_string(
        method=values["method"],
        path=values["path"],
        canonical_query=build_canonical_query(values["query_string"]),
        body_sha256=compute_body_sha256(body),
        timestamp=values["timestamp"],
        nonce=values["nonce"],
        kid=values["kid"],
        actor_ref=values["actor_ref"],
        request_id=values["request_id"],
        idempotency_key=values["idempotency_key"],
    )
    values["signature_header"] = compute_signature(canonical, TEST_SECRET)
    values["secret"] = TEST_SECRET
    return values


def test_canonical_query_is_sorted() -> None:
    assert build_canonical_query("preview=1&lang=zh") == "lang=zh&preview=1"
    assert build_canonical_query("") == ""
    assert build_canonical_query(None) == ""


def test_body_hash_uses_sha256() -> None:
    assert compute_body_sha256(b"hello") == hashlib.sha256(b"hello").hexdigest()


def test_canonical_string_has_stable_ten_line_contract() -> None:
    values = _request()
    canonical = build_canonical_string(
        method=values["method"],
        path=values["path"],
        canonical_query=build_canonical_query(values["query_string"]),
        body_sha256=compute_body_sha256(values["body_bytes"]),
        timestamp=values["timestamp"],
        nonce=values["nonce"],
        kid=values["kid"],
        actor_ref=values["actor_ref"],
        request_id=values["request_id"],
        idempotency_key=values["idempotency_key"],
    )
    lines = canonical.split("\n")
    assert len(lines) == 10
    assert lines[0] == "POST"
    assert lines[1] == values["path"]
    assert lines[2] == "lang=zh&preview=1"
    assert lines[-1] == "test-task"


def test_signature_round_trip_and_format() -> None:
    values = _request()
    assert values["signature_header"].startswith(SIGNATURE_PREFIX)
    assert len(values["signature_header"][len(SIGNATURE_PREFIX):]) == 64
    assert verify_signature(**values)


def test_modified_request_fails_verification() -> None:
    values = _request()
    modified = {**values, "path": values["path"] + "/changed"}
    assert not verify_signature(**modified)


def test_verification_uses_constant_time_comparison() -> None:
    source = inspect.getsource(verify_signature)
    assert "hmac.compare_digest" in source


def test_nonce_store_rejects_replay() -> None:
    store = InMemoryNonceStore()
    assert store.claim("test-key:test-nonce", 300) is True
    assert store.claim("test-key:test-nonce", 300) is False


def test_expired_nonce_can_be_claimed_again() -> None:
    store = InMemoryNonceStore()
    assert store.claim("test-key:test-nonce", 0) is True
    time.sleep(0.01)
    assert store.claim("test-key:test-nonce", 300) is True
