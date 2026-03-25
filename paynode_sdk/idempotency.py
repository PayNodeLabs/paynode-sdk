import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

class IdempotencyStore(ABC):
    @abstractmethod
    async def check_and_set(self, tx_hash: str, ttl_seconds: int) -> bool:
        """
        Returns True if hash was newly set, False if already exists and not expired.
        """
        pass

    @abstractmethod
    async def delete(self, tx_hash: str) -> None:
        """
        Deletes a transaction hash from the store.
        Used for rolling back a lock if subsequent verification fails.
        """
        pass

class MemoryIdempotencyStore(IdempotencyStore):
    def __init__(self):
        self.cache: Dict[str, float] = {}

    async def check_and_set(self, tx_hash: str, ttl_seconds: int) -> bool:
        now = time.time()
        expiry = self.cache.get(tx_hash)

        if expiry and expiry > now:
            return False

        self.cache[tx_hash] = now + ttl_seconds
        self._cleanup()
        return True

    async def delete(self, tx_hash: str) -> None:
        self.cache.pop(tx_hash, None)

    def _cleanup(self):
        now = time.time()
        # Simple cleanup logic: remove expired entries
        expired_keys = [k for k, v in self.cache.items() if v <= now]
        for k in expired_keys:
            del self.cache[k]


class RedisIdempotencyStore(IdempotencyStore):
    """
    Production-ready implementation using Redis.
    Uses `SET txHash 1 NX EX ttlSeconds` for atomic check-and-set.

    Requires: pip install redis
    Usage:
        import redis
        store = RedisIdempotencyStore(redis.Redis(host='localhost', port=6379))
    """
    def __init__(self, redis_client, prefix: str = "paynode:tx:"):
        self.redis = redis_client
        self.prefix = prefix

    async def check_and_set(self, tx_hash: str, ttl_seconds: int) -> bool:
        key = f"{self.prefix}{tx_hash}"
        return bool(self.redis.set(key, 1, ex=ttl_seconds, nx=True))

    async def delete(self, tx_hash: str) -> None:
        key = f"{self.prefix}{tx_hash}"
        self.redis.delete(key)
