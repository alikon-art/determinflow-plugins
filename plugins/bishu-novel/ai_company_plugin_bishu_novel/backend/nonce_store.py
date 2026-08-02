"""Nonce 去重存储 — 防止请求重放攻击。

接口设计原则:
  - 使用单个原子方法 claim()，而非 seen()+add() 两步，避免 TOCTOU 竞态窗口。
  - InMemory 实现适用单进程部署（uvicorn 无 --workers 参数）。
  - Redis 实现预留：SET key 1 NX EX <ttl> 的返回值天然原子。

Nonce key 格式: {kid}:{nonce}
TTL 建议: 时间窗 + 余量（如 300s + 60s = 360s）
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class NonceStore(ABC):
    """Nonce 去重存储抽象接口。"""

    @abstractmethod
    def claim(self, key: str, ttl: int) -> bool:
        """原子地检查和注册 nonce。

        Args:
            key: nonce 键，格式 "{kid}:{nonce}"
            ttl: 过期时间（秒）

        Returns:
            True — 首次见到该 nonce，已写入
            False — nonce 已存在（重放）
        """
        ...


class InMemoryNonceStore(NonceStore):
    """进程内 TTL 缓存实现，适用于单进程部署。

    使用 dict + timestamp 记录实现简单 TTL。
    后台清理由每次 claim 时触发，惰性淘汰过期条目。
    """

    def __init__(self):
        # {key: expire_timestamp}
        self._store: dict[str, float] = {}
        # 超过此数量时触发清理
        self._cleanup_threshold = 100_000

    def claim(self, key: str, ttl: int) -> bool:
        now = time.monotonic()

        # 惰性清理：每 claim 时先检查自身是否过期，顺便清理少量过期条目
        existing = self._store.get(key)
        if existing is not None and existing > now:
            return False  # 重放

        # 周期性清理过期条目
        if len(self._store) > self._cleanup_threshold:
            self._purge_expired(now)

        # 写入
        self._store[key] = now + ttl
        return True

    def _purge_expired(self, now: float):
        """清理所有过期条目。"""
        expired = [k for k, exp in self._store.items() if exp <= now]
        for k in expired:
            del self._store[k]
        if expired:
            logger.debug("NonceStore 清理了 %d 条过期 nonce", len(expired))

    def __len__(self) -> int:
        """返回当前存储条目数（用于监控）。"""
        return len(self._store)


class RedisNonceStore(NonceStore):
    """Redis 实现 — 多进程/多实例部署用。

    使用时需安装 redis 库: pip install redis
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise ImportError(
                "RedisNonceStore 需要安装 redis 库: pip install redis"
            )
        self._redis_url = redis_url
        self._redis: "aioredis.Redis | None" = None

    async def _ensure_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def claim(self, key: str, ttl: int) -> bool:
        r = await self._ensure_redis()
        # SET key 1 NX EX ttl → 返回 True（首次）或 None（已存在）
        result = await r.set(key, b"1", nx=True, ex=ttl)
        return result is True
