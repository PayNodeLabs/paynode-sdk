import hmac
import hashlib
import time
from datetime import datetime
import logging

logger = logging.getLogger("paynode_sdk.signature")

def verify_market_signature(
    signature: str,
    order_id: str,
    timestamp: str,
    shared_secret: str,
    now: float = None,
    drift_window: int = 300  # 5 minutes in seconds
) -> bool:
    """
    Verifies the HMAC-SHA256 signature from PayNode Market Proxy.
    
    Args:
        signature: Received hex signature
        order_id: The order ID or request ID
        timestamp: ISO string or millisecond timestamp
        shared_secret: Merchant-specific shared secret
        now: Current time in seconds (for testing)
        drift_window: Allowed drift in seconds
        
    Returns:
        bool: True if signature is valid and within drift window
    """
    if not all([signature, order_id, timestamp, shared_secret]):
        return False

    try:
        # 1. Parse timestamp
        check_time = now or time.time()
        
        try:
            # Try ISO format (matching JS new Date(timestamp))
            ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            ts_seconds = ts_dt.timestamp()
        except ValueError:
            # Try milliseconds (JS numeric timestamp)
            try:
                ts_seconds = int(timestamp) / 1000.0
            except ValueError:
                return False

        # 2. Check for timestamp drift
        drift = abs(check_time - ts_seconds)
        if drift > drift_window:
            logger.warning(f"[PayNode-SDK] Signature timestamp drift too high: {int(drift * 1000)}ms")
            return False

        # 3. Calculate expected signature
        # Formula: orderId + ":" + timestamp
        msg = f"{order_id}:{timestamp}".encode("utf-8")
        key = shared_secret.encode("utf-8")
        
        expected_sig = hmac.new(key, msg, hashlib.sha256).hexdigest()
        
        # 4. Constant-time comparison
        return hmac.compare_digest(signature.lower(), expected_sig.lower())

    except Exception as e:
        logger.error(f"[PayNode-SDK] Error verifying market signature: {e}")
        return False
