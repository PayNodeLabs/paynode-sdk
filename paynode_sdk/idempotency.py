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

    def _cleanup(self):
        now = time.time()
        # Simple cleanup logic: remove expired entries
        expired_keys = [k for k, v in self.cache.items() if v <= now]
        for k in expired_keys:
            del self.cache[k]
