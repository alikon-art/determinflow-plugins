"""Engine Auth 中间件 — 端到端集成测试。

使用 httpx 异步测试客户端，验证中间件的 observe 和 enforce 行为。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_company_plugin_bishu_novel.backend.engine_signing import (
    compute_signature,
    build_canonical_string,
    build_canonical_query,
    compute_body_sha256,
)
from ai_company_plugin_bishu_novel.backend.engine_auth_middleware import EngineAuthMiddleware
from ai_company_plugin_bishu_novel.backend.nonce_store import InMemoryNonceStore

# ═══════════════════════════════════════════════════════════
# 测试参数（与测试向量一致）
# ═══════════════════════════════════════════════════════════

KID = "portal-2026q2"
SECRET = "test-only-signing-key-" + ("x" * 48)  # pragma: allowlist secret


def _make_signing_headers(
    method: str,
    path: str,
    query_string: str,
    body_bytes: bytes,
    kid: str = KID,
    secret: str = SECRET,
    ts: int | None = None,
    nonce: str | None = None,
    actor_ref: str = "",
    request_id: str = "",
    idempotency_key: str = "",
) -> dict[str, str]:
    """生成合法的签名头。"""
    import secrets

    if ts is None:
        ts = int(time.time())
    if nonce is None:
        nonce = secrets.token_hex(16)

    body_sha256 = compute_body_sha256(body_bytes)
    canonical_query = build_canonical_query(query_string)
    canonical = build_canonical_string(
        method=method,
        path=path,
        canonical_query=canonical_query,
        body_sha256=body_sha256,
        timestamp=str(ts),
        nonce=nonce,
        kid=kid,
        actor_ref=actor_ref,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
    sig = compute_signature(canonical, secret)

    headers = {
        "X-Key-Id": kid,
        "X-Timestamp": str(ts),
        "X-Nonce": nonce,
        "X-Signature": sig,
    }
    if actor_ref:
        headers["X-Actor-Ref"] = actor_ref
    if request_id:
        headers["X-Request-Id"] = request_id
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


# ═══════════════════════════════════════════════════════════
# 测试 App
# ═══════════════════════════════════════════════════════════

def _make_app(engine_sign_enabled: bool, engine_sign_mode: str, keys: str = ""):
    """创建带中间件的 FastAPI 测试应用。"""
    from ai_company_plugin_bishu_novel.backend import config as cfg

    # 打补丁：临时覆盖模块级配置
    cfg.ENGINE_SIGN_ENABLED = engine_sign_enabled
    cfg.ENGINE_SIGN_MODE = engine_sign_mode
    cfg.ENGINE_SIGN_KEYS = keys
    cfg.ENGINE_SIGN_CLOCK_SKEW_SECONDS = 300

    app = FastAPI()
    app.add_middleware(EngineAuthMiddleware)

    @app.get("/api/v1/novel/books/{book_id}")
    async def get_book(book_id: str):
        return {"book_id": book_id, "title": "Test Book"}

    @app.post("/api/v1/novel/books/{book_id}/chapters/{num}/generate")
    async def generate_chapter(book_id: str, num: int):
        return {"status": "ok", "book_id": book_id, "chapter": num}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/novel/jobs/{job_id}/stream")
    async def stream_job(job_id: str):
        return {"job_id": job_id}

    return app


# ═══════════════════════════════════════════════════════════
# Observe 模式测试
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def observe_client():
    app = _make_app(
        engine_sign_enabled=True,
        engine_sign_mode="observe",
        keys=f"{KID}:{SECRET}",
    )
    # 重置计数器
    from ai_company_plugin_bishu_novel.backend.engine_auth_middleware import _observe_counter
    for k in _observe_counter:
        _observe_counter[k] = 0
    return TestClient(app)


def test_observe_valid_request(observe_client):
    """observe 模式: 合法签名 → 返回正常数据"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
    )
    resp = observe_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["book_id"] == "bk_demo"


def test_observe_no_signature_still_passes(observe_client):
    """observe 模式: 无签名头 → 仍返回正常数据（但记录警告）"""
    resp = observe_client.get("/api/v1/novel/books/bk_demo")
    assert resp.status_code == 200
    assert resp.json()["book_id"] == "bk_demo"


def test_observe_bad_signature_still_passes(observe_client):
    """observe 模式: 篡改签名 → 仍返回正常数据"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
    )
    # 篡改签名
    headers["X-Signature"] = "v1=0000000000000000000000000000000000000000000000000000000000000000"
    resp = observe_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 200


def test_observe_non_novel_path(observe_client):
    """observe 模式: /health 路径不校验"""
    resp = observe_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════
# Enforce 模式测试
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def enforce_client():
    app = _make_app(
        engine_sign_enabled=True,
        engine_sign_mode="enforce",
        keys=f"{KID}:{SECRET}",
    )
    return TestClient(app)


def test_enforce_valid_request(enforce_client):
    """enforce 模式: 合法签名 → 200"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
    )
    resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 200


def test_enforce_valid_post(enforce_client):
    """enforce 模式: POST 合法签名 → 200"""
    body_bytes = json.dumps(
        {"human_intent": "继续", "target_word_count": "4000"},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = _make_signing_headers(
        method="POST",
        path="/api/v1/novel/books/bk_demo/chapters/1/generate",
        query_string="",
        body_bytes=body_bytes,
    )
    import secrets
    # 每次用唯一 nonce
    headers["X-Nonce"] = secrets.token_hex(16)
    # 重新计算签名
    body_sha256 = compute_body_sha256(body_bytes)
    canonical_query = build_canonical_query("")
    canonical = build_canonical_string(
        method="POST",
        path="/api/v1/novel/books/bk_demo/chapters/1/generate",
        canonical_query=canonical_query,
        body_sha256=body_sha256,
        timestamp=headers["X-Timestamp"],
        nonce=headers["X-Nonce"],
        kid=KID,
    )
    headers["X-Signature"] = compute_signature(canonical, SECRET)

    resp = enforce_client.post(
        "/api/v1/novel/books/bk_demo/chapters/1/generate",
        content=body_bytes,
        headers=headers,
    )
    assert resp.status_code == 200


def test_enforce_no_signature_401(enforce_client):
    """enforce 模式: 无签名头 → 401"""
    resp = enforce_client.get("/api/v1/novel/books/bk_demo")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "missing_headers"


def test_enforce_bad_signature_401(enforce_client):
    """enforce 模式: 错误签名 → 401"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
    )
    headers["X-Signature"] = "v1=deadbeef" + "0" * 48
    resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "bad_signature"


def test_enforce_unknown_kid_401(enforce_client):
    """enforce 模式: 未知 kid → 401"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
        kid="unknown-kid",
    )
    resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "unknown_kid"


def test_enforce_clock_skew_401(enforce_client):
    """enforce 模式: 过期时间戳 → 401"""
    past_ts = int(time.time()) - 600  # 10 分钟前
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
        ts=past_ts,
    )
    resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "clock_skew"


def test_enforce_future_timestamp_401(enforce_client):
    """enforce 模式: 未来时间戳 → 401"""
    future_ts = int(time.time()) + 600  # 10 分钟后
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
        ts=future_ts,
    )
    resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "clock_skew"


def test_enforce_nonce_replay_409(enforce_client):
    """enforce 模式: nonce 重放 → 409"""
    nonce = "deadbeefdeadbeefdeadbeefdeadbeef"
    headers = _make_signing_headers(
        method="POST",
        path="/api/v1/novel/books/bk_demo/chapters/1/generate",
        query_string="",
        body_bytes=b"{}",
        nonce=nonce,
    )
    # 第一次 → 200
    resp1 = enforce_client.post(
        "/api/v1/novel/books/bk_demo/chapters/1/generate",
        content=b"{}",
        headers=headers,
    )
    assert resp1.status_code == 200

    # 第二次 → 409
    resp2 = enforce_client.post(
        "/api/v1/novel/books/bk_demo/chapters/1/generate",
        content=b"{}",
        headers=headers,
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"] == "nonce_replay"


def test_enforce_get_nonce_not_dedup(enforce_client):
    """enforce 模式: GET 不参与 nonce 去重"""
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_demo",
        query_string="",
        body_bytes=b"",
        nonce="get_nonce_00000000000000000000",
    )
    # 多次相同 nonce 的 GET → 每次都是 200（不校验 nonce 去重）
    for _ in range(3):
        resp = enforce_client.get("/api/v1/novel/books/bk_demo", headers=headers)
        assert resp.status_code == 200


def test_enforce_non_novel_path_not_affected(enforce_client):
    """enforce 模式: /health 不校验 → 200"""
    resp = enforce_client.get("/health")
    assert resp.status_code == 200


def test_enforce_tampered_path_401(enforce_client):
    """enforce 模式: path 签名与实际请求不一致 → 401"""
    # 对 path A 签名，请求 path B
    headers = _make_signing_headers(
        method="GET",
        path="/api/v1/novel/books/bk_legit",
        query_string="",
        body_bytes=b"",
    )
    resp = enforce_client.get("/api/v1/novel/books/bk_attacker", headers=headers)
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# Signing Disabled 测试
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def disabled_client():
    app = _make_app(
        engine_sign_enabled=False,
        engine_sign_mode="enforce",
        keys="",
    )
    return TestClient(app)


def test_disabled_passes_all(disabled_client):
    """签名未启用时所有请求直接放行。"""
    resp = disabled_client.get("/api/v1/novel/books/bk_demo")
    assert resp.status_code == 200

    resp = disabled_client.post(
        "/api/v1/novel/books/bk_demo/chapters/1/generate",
        content=b"{}",
    )
    assert resp.status_code == 200
