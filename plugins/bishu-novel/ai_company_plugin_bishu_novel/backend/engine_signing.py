"""Engine API 请求签名验证 — 纯函数，无副作用。

与门户侧 backend/app/services/engine_signing.py 共享同一套 canonical 契约。

Canonical 串 10 行，以 \\n 连接:
    {method}\\n{path}\\n{canonical_query}\\n{body_sha256}\\n{ts}\\n{nonce}\\n{kid}\\n
    {actor_ref}\\n{request_id}\\n{idempotency_key}

签名算法: X-Signature = "v1=" + hex(HMAC-SHA256(secret, canonical))
比较使用 hmac.compare_digest（常数时间，防时序侧信道）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from urllib.parse import parse_qsl, urlencode

logger = logging.getLogger(__name__)

# 签名版本前缀
SIGNATURE_PREFIX = "v1="


def build_canonical_query(query_string: str) -> str:
    """将 raw query string 规范化为按 key 字母序升序的 query。

    规则:
      - 按 key 升序排列
      - 同 key 多值保留原始顺序
      - 空串 → 空串
      - 输出不含前导 ?

    Args:
        query_string: request.url.query 的原始值 (不含 ?)

    Returns:
        规范化后的 query string，例如 "lang=zh&preview=1"
    """
    if not query_string:
        return ""

    # parse_qsl 保留同 key 多值的顺序
    pairs = parse_qsl(query_string, keep_blank_values=True)
    if not pairs:
        return ""

    # 按 key 升序
    pairs.sort(key=lambda kv: kv[0])
    return urlencode(pairs)


def build_canonical_string(
    method: str,
    path: str,
    canonical_query: str,
    body_sha256: str,
    timestamp: str,
    nonce: str,
    kid: str,
    actor_ref: str = "",
    request_id: str = "",
    idempotency_key: str = "",
) -> str:
    """构建待签名的规范化字符串（10 行 \\n 连接）。

    行数恒为 10，三个业务头缺失时为空串，不省略行。

    Args:
        method: HTTP 方法（如 POST），会转为大写
        path: 完整路径（含 /api/v1/novel 前缀），来自 request.url.path
        canonical_query: build_canonical_query() 的规范化结果
        body_sha256: 请求体的 hex sha256
        timestamp: Unix 秒（字符串）
        nonce: 32 字符 hex
        kid: 密钥标识
        actor_ref: X-Actor-Ref 值，缺失为空串
        request_id: X-Request-Id 值，缺失为空串
        idempotency_key: Idempotency-Key 值，缺失为空串

    Returns:
        10 行 \\n 分隔的规范化字符串
    """
    return "\n".join([
        method.upper(),
        path,
        canonical_query,
        body_sha256,
        timestamp,
        nonce,
        kid,
        actor_ref or "",
        request_id or "",
        idempotency_key or "",
    ])


def compute_body_sha256(body_bytes: bytes) -> str:
    """计算请求体的 sha256 hex 摘要。

    Args:
        body_bytes: 原始请求体字节。空体传入 b""。

    Returns:
        64 位小写 hex 字符串
    """
    return hashlib.sha256(body_bytes).hexdigest()


def compute_signature(canonical_string: str, secret: str) -> str:
    """计算 HMAC-SHA256 签名，返回带版本前缀的签名值。

    Args:
        canonical_string: build_canonical_string() 的输出
        secret: UTF-8 签名密钥字符串

    Returns:
        "v1=<hex>" 格式的签名字符串
    """
    sig = hmac.new(
        secret.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{sig}"


def verify_signature(
    *,
    method: str,
    path: str,
    query_string: str,
    body_bytes: bytes,
    timestamp: str,
    nonce: str,
    kid: str,
    signature_header: str,
    secret: str,
    actor_ref: str = "",
    request_id: str = "",
    idempotency_key: str = "",
) -> bool:
    """验签完整流程：构建 canonical → 计算签名 → 常数时间比对。

    Args:
        method: HTTP 方法
        path: 请求路径（request.url.path）
        query_string: 原始 query string（request.url.query，不含 ?）
        body_bytes: 请求体原始字节
        timestamp: X-Timestamp header
        nonce: X-Nonce header
        kid: X-Key-Id header
        signature_header: X-Signature header（完整值，含 "v1=" 前缀）
        secret: 该 kid 对应的密钥
        actor_ref: X-Actor-Ref header
        request_id: X-Request-Id header
        idempotency_key: Idempotency-Key header

    Returns:
        True 表示签名匹配
    """
    canonical_query = build_canonical_query(query_string)
    body_sha256 = compute_body_sha256(body_bytes)

    canonical = build_canonical_string(
        method=method,
        path=path,
        canonical_query=canonical_query,
        body_sha256=body_sha256,
        timestamp=timestamp,
        nonce=nonce,
        kid=kid,
        actor_ref=actor_ref,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )

    expected = compute_signature(canonical, secret)
    return hmac.compare_digest(expected, signature_header)


# ───────────────────────────────────────────────
# 请求头解析辅助
# ───────────────────────────────────────────────

# 签名相关的 header 名（小写）
HEADER_KEY_ID = "x-key-id"
HEADER_TIMESTAMP = "x-timestamp"
HEADER_NONCE = "x-nonce"
HEADER_SIGNATURE = "x-signature"
HEADER_ACTOR_REF = "x-actor-ref"
HEADER_REQUEST_ID = "x-request-id"
HEADER_IDEMPOTENCY_KEY = "idempotency-key"

REQUIRED_SIGNING_HEADERS = (
    HEADER_KEY_ID,
    HEADER_TIMESTAMP,
    HEADER_NONCE,
    HEADER_SIGNATURE,
)


def parse_signing_headers(headers) -> dict[str, str | None]:
    """从请求头中提取签名相关字段。

    Headers 参数可以是 dict 或 Starlette/MutableHeaders 对象。

    Returns:
        {key_id, timestamp, nonce, signature, actor_ref, request_id, idempotency_key}
        每个值都可能为 None
    """
    return {
        "key_id": headers.get(HEADER_KEY_ID),
        "timestamp": headers.get(HEADER_TIMESTAMP),
        "nonce": headers.get(HEADER_NONCE),
        "signature": headers.get(HEADER_SIGNATURE),
        "actor_ref": headers.get(HEADER_ACTOR_REF) or "",
        "request_id": headers.get(HEADER_REQUEST_ID) or "",
        "idempotency_key": headers.get(HEADER_IDEMPOTENCY_KEY) or "",
    }
