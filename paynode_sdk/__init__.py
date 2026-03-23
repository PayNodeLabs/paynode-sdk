import warnings
import logging

# Silence upstream library deprecation warnings from web3's websocket dependency
# to ensure a clean experience for PayNode SDK users.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.legacy")

from .middleware import PayNodeMiddleware, x402_gate
from .verifier import PayNodeVerifier
from .errors import ErrorCode, PayNodeException
from .idempotency import IdempotencyStore, MemoryIdempotencyStore
from .webhook import PayNodeWebhookNotifier, PaymentEvent
from .client import PayNodeAgentClient
from .constants import (
    PAYNODE_ROUTER_ADDRESS,
    PAYNODE_ROUTER_ADDRESS_SANDBOX,
    BASE_USDC_ADDRESS,
    BASE_USDC_ADDRESS_SANDBOX,
    ACCEPTED_TOKENS,
    MIN_PAYMENT_AMOUNT
)

__all__ = [
    "PayNodeMiddleware", "x402_gate", "PayNodeVerifier", "ErrorCode", "PayNodeException",
    "IdempotencyStore", "MemoryIdempotencyStore",
    "PayNodeWebhookNotifier", "PaymentEvent",
    "PayNodeAgentClient",
    "PAYNODE_ROUTER_ADDRESS", "PAYNODE_ROUTER_ADDRESS_SANDBOX",
    "BASE_USDC_ADDRESS", "BASE_USDC_ADDRESS_SANDBOX",
    "ACCEPTED_TOKENS", "MIN_PAYMENT_AMOUNT"
]
