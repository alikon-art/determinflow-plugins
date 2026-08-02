"""Engine API 请求签名验证 — ASGI 中间件。

纯 ASGI middleware（非 BaseHTTPMiddleware），确保 body 读取后下游仍可消费。

职责:
  1. 仅拦截 /api/v1/novel/* 路径
  2. 读取原始请求体 → 计算 sha256 → 重新挂回 receive
  3. 提取签名头 → 构建 canonical → HMAC 验签
  4. 时间窗校验（防过期/未来时间戳）
  5. Nonce 去重（仅 POST/PUT/DELETE）
  6. observe 模式：全流程校验但始终放行，打点计数
  7. enforce 模式：失败返回 401/409，阻止请求

错误响应体格式:
    {"error": "<reason>", "message": "...", "details": {...}}
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Callable

from . import config as engine_cfg
from .engine_signing import (
    HEADER_KEY_ID,
    HEADER_TIMESTAMP,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    REQUIRED_SIGNING_HEADERS,
    parse_signing_headers,
    verify_signature,
)
from .nonce_store import InMemoryNonceStore, NonceStore

logger = logging.getLogger(__name__)

# observe 模式计数器（module-level，单进程可见）
_observe_counter: dict[str, int] = {
    "pass": 0,
    "missing_headers": 0,
    "unknown_kid": 0,
    "clock_skew": 0,
    "nonce_replay": 0,
    "bad_signature": 0,
    "skipped_non_novel": 0,
}

# 错误原因枚举
REASON_MISSING_HEADERS = "missing_headers"
REASON_UNKNOWN_KID = "unknown_kid"
REASON_CLOCK_SKEW = "clock_skew"
REASON_NONCE_REPLAY = "nonce_replay"
REASON_BAD_SIGNATURE = "bad_signature"

# 需要 nonce 去重的方法
METHODS_WITH_NONCE_DEDUP = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _json_error_response(
    status_code: int,
    error: str,
    message: str,
    details: dict | None = None,
) -> tuple[int, bytes]:
    """构建 JSON 错误响应体。"""
    body = {
        "error": error,
        "message": message,
    }
    if details:
        body["details"] = details
    return status_code, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def _read_body(receive: Callable) -> bytearray:
    """从 ASGI receive 读取完整请求体。

    Returns:
        请求体的所有字节。空体返回空 bytearray。
    """
    body_chunks: list[bytes] = []
    more_body = True

    while more_body:
        message = await receive()
        if message["type"] != "http.request":
            # 非请求消息（如 disconnect），忽略
            continue

        body_chunks.append(message.get("body", b""))
        more_body = message.get("more_body", False)

    return bytearray().join(body_chunks)


def _make_receive_with_body(body_bytes: bytearray, original_receive: Callable):
    """创建一个新的 receive 函数，首次调用返回缓存的 body，后续调用代理到原始 receive。"""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {
                "type": "http.request",
                "body": bytes(body_bytes),
                "more_body": False,
            }
        return await original_receive()

    return receive


class EngineAuthMiddleware:
    """Engine API 签名验证中间件。

    ASGI 协议级别，不继承 BaseHTTPMiddleware。
    """

    ENFORCE_SKIP_PREFIX = b"/api/v1/novel"

    def __init__(self, app, nonce_store: NonceStore | None = None):
        self.app = app
        self._nonce_store = nonce_store or InMemoryNonceStore()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # 非 HTTP 请求（如 WebSocket），直接透传
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")

        # 仅对 /api/v1/novel/* 做签名校验
        if not path.startswith("/api/v1/novel"):
            if engine_cfg.ENGINE_SIGN_ENABLED:
                _observe_counter["skipped_non_novel"] += 1
            await self.app(scope, receive, send)
            return

        # 签名未启用 → 直接放行（开发环境）
        if not engine_cfg.ENGINE_SIGN_ENABLED:
            await self.app(scope, receive, send)
            return

        # ── 读取 body ──
        body_bytes = await _read_body(receive)
        new_receive = _make_receive_with_body(body_bytes, receive)

        # ── 验证 ──
        result = self._verify(scope, bytes(body_bytes), method, path)

        if result["ok"]:
            _observe_counter["pass"] += 1
            await self.app(scope, new_receive, send)
            return

        # ── observe 模式: 记录但放行 ──
        if engine_cfg.ENGINE_SIGN_MODE == "observe":
            reason = result["reason"]
            _observe_counter[reason] = _observe_counter.get(reason, 0) + 1
            logger.warning(
                "ENGINE_SIGN[observe] 验签失败: reason=%s path=%s method=%s details=%s",
                reason,
                path,
                method,
                result.get("details", {}),
            )
            # 每 100 次打印一次计数摘要
            total = sum(v for k, v in _observe_counter.items() if k != "skipped_non_novel" and v > 0)
            if _observe_counter["pass"] > 0 and _observe_counter["pass"] % 100 == 0:
                logger.info("ENGINE_SIGN[observe] 计数器: %s", dict(_observe_counter))
            await self.app(scope, new_receive, send)
            return

        # ── enforce 模式: 拒绝 ──
        reason = result["reason"]
        status_code = result["status_code"]
        error_body = result["error_body"]
        logger.warning(
            "ENGINE_SIGN[enforce] 拒绝请求: reason=%s path=%s method=%s",
            reason,
            path,
            method,
        )
        await self._send_error(send, status_code, error_body)

    def _verify(self, scope: dict, body_bytes: bytes, method: str, path: str) -> dict:
        """执行签名验证全流程。

        Returns:
            {"ok": True} 或 {"ok": False, "reason": ..., "status_code": ..., "error_body": ..., "details": ...}
        """
        headers = scope.get("headers", [])
        header_dict = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}

        # 1. 必需头存在
        parsed = parse_signing_headers(header_dict)
        missing = [h for h in REQUIRED_SIGNING_HEADERS if not parsed.get(_header_to_key(h))]
        if missing:
            status, body = _json_error_response(
                401,
                REASON_MISSING_HEADERS,
                f"缺少必需的签名头: {', '.join(missing)}",
                {"missing_headers": missing},
            )
            return {
                "ok": False,
                "reason": REASON_MISSING_HEADERS,
                "status_code": status,
                "error_body": body,
                "details": {"missing_headers": missing},
            }

        kid = parsed["key_id"]
        timestamp_str = parsed["timestamp"]
        nonce = parsed["nonce"]
        signature = parsed["signature"]
        actor_ref = parsed["actor_ref"]
        request_id = parsed["request_id"]
        idempotency_key = parsed["idempotency_key"]

        # 2. kid 已知
        keys = engine_cfg.get_engine_signing_keys()
        secret = keys.get(kid) if kid else None
        if not secret:
            status, body = _json_error_response(
                401,
                REASON_UNKNOWN_KID,
                f"未知的密钥标识: {kid}",
                {"kid": kid},
            )
            return {
                "ok": False,
                "reason": REASON_UNKNOWN_KID,
                "status_code": status,
                "error_body": body,
                "details": {"kid": kid},
            }

        # 3. 时间窗
        try:
            req_ts = int(timestamp_str)
        except (ValueError, TypeError):
            status, body = _json_error_response(
                401,
                REASON_CLOCK_SKEW,
                f"无效的时间戳: {timestamp_str}",
                {"timestamp": timestamp_str},
            )
            return {
                "ok": False,
                "reason": REASON_CLOCK_SKEW,
                "status_code": status,
                "error_body": body,
                "details": {"timestamp": timestamp_str},
            }

        now_ts = int(time.time())
        clock_skew = engine_cfg.ENGINE_SIGN_CLOCK_SKEW_SECONDS
        skew = abs(now_ts - req_ts)
        if skew > clock_skew:
            status, body = _json_error_response(
                401,
                REASON_CLOCK_SKEW,
                f"时间戳偏差超过允许范围 ({skew}s > {clock_skew}s)",
                {
                    "skew_seconds": skew,
                    "max_skew_seconds": clock_skew,
                },
            )
            return {
                "ok": False,
                "reason": REASON_CLOCK_SKEW,
                "status_code": status,
                "error_body": body,
                "details": {"skew_seconds": skew, "max_skew_seconds": clock_skew},
            }

        # 4. nonce 去重（仅 POST/PUT/DELETE/PATCH）
        if method.upper() in METHODS_WITH_NONCE_DEDUP:
            nonce_key = f"{kid}:{nonce}"
            if not self._nonce_store.claim(nonce_key, engine_cfg.ENGINE_SIGN_NONCE_TTL_SECONDS):
                status, body = _json_error_response(
                    409,
                    REASON_NONCE_REPLAY,
                    "请求重放: 该 nonce 已被使用",
                    {"kid": kid, "nonce_prefix": nonce[:8] + "..."},
                )
                return {
                    "ok": False,
                    "reason": REASON_NONCE_REPLAY,
                    "status_code": status,
                    "error_body": body,
                    "details": {"kid": kid, "nonce_prefix": nonce[:8] + "..."},
                }

        # 5. 验签
        query_string = (scope.get("query_string") or b"").decode("latin-1")

        valid = verify_signature(
            method=method,
            path=path,
            query_string=query_string,
            body_bytes=body_bytes,
            timestamp=timestamp_str,
            nonce=nonce,
            kid=kid,
            signature_header=signature,
            secret=secret,
            actor_ref=actor_ref,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

        if not valid:
            status, body = _json_error_response(
                401,
                REASON_BAD_SIGNATURE,
                "签名验证失败",
                {"kid": kid},
            )
            return {
                "ok": False,
                "reason": REASON_BAD_SIGNATURE,
                "status_code": status,
                "error_body": body,
                "details": {"kid": kid},
            }

        return {"ok": True}

    async def _send_error(self, send, status_code: int, body: bytes):
        """发送 ASGI HTTP 错误响应。"""
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })


def _header_to_key(header_name: str) -> str:
    """将 header 名映射到 parse_signing_headers 返回字典的 key 名。"""
    mapping = {
        "x-key-id": "key_id",
        "x-timestamp": "timestamp",
        "x-nonce": "nonce",
        "x-signature": "signature",
    }
    return mapping.get(header_name, header_name)


def get_observe_counters() -> dict[str, int]:
    """获取 observe 模式计数器快照（用于监控/调试）。"""
    return dict(_observe_counter)
