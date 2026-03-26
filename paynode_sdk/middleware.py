import time
import base64
import json
import logging
from typing import Optional, Callable, Any
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from .verifier import PayNodeVerifier
from .errors import ErrorCode
from .idempotency import IdempotencyStore
from .constants import (
    BASE_RPC_URLS, 
    PAYNODE_ROUTER_ADDRESS, 
    BASE_USDC_ADDRESS, 
    BASE_USDC_DECIMALS
)

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("paynode_sdk.middleware")

class PayNodeMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        merchant_address: str,
        price: str,
        contract_address: str = PAYNODE_ROUTER_ADDRESS,
        chain_id: int = 8453,
        currency: str = "USDC",
        token_address: str = BASE_USDC_ADDRESS,
        decimals: int = BASE_USDC_DECIMALS,
        rpc_urls: list | str = BASE_RPC_URLS,
        store: Optional[IdempotencyStore] = None,
        generate_order_id: Optional[Callable[[Request], str]] = None,
        **kwargs
    ):
        super().__init__(app)
        # The Verifier holds the state of the idempotency store
        self.verifier = PayNodeVerifier(rpc_urls=rpc_urls, contract_address=contract_address, chain_id=chain_id, store=store)
        self.merchant_address = merchant_address
        self.contract_address = contract_address
        self.currency = currency
        self.token_address = token_address
        self.price = price
        self.decimals = decimals
        self.chain_id = chain_id
        self.generate_order_id = generate_order_id or (lambda r: f"agent_py_{int(time.time() * 1000)}")

        # DEV-2 FIX: Avoid float precision risks by using integer arithmetic or decimal string parsing
        if "." in price:
            parts = price.split(".")
            integer_part = parts[0]
            fraction_part = parts[1][:decimals].ljust(decimals, "0")
            self.amount_int = int(integer_part + fraction_part)
        else:
            self.amount_int = int(price) * (10 ** decimals)
        self.description = kwargs.get('description', "Protected Resource")
        self.max_timeout_seconds = kwargs.get('max_timeout_seconds', 3600)

    async def dispatch(self, request: Request, call_next):
        v2_payload_header = request.headers.get('X-402-Payload')
        order_id = request.headers.get('X-402-Order-Id')

        if not order_id:
            order_id = self.generate_order_id(request)

        # Handle x402 v2 Unified Payload
        unified_payload = None
        if v2_payload_header:
            try:
                unified_payload = json.loads(base64.b64decode(v2_payload_header.encode()).decode())
            except Exception as e:
                logger.error(f"❌ [PayNode-Middleware] Failed to decode X-402-Payload header: {e}")

        if unified_payload:
            try:
                result = await self.verifier.verify(
                    unified_payload,
                    {
                        "merchantAddress": self.merchant_address,
                        "tokenAddress": self.token_address,
                        "amount": str(self.amount_int),
                        "orderId": order_id
                    },
                    # BUG-1 FIX: extra should come from our own config (v2Response schema), not the agent's payload
                    {
                        "name": self.currency,
                        "version": "2" # USDC v2
                    } if unified_payload.get("type") == "eip3009" else {}
                )
                if result.get("isValid"):
                    request.state.paynode = {"unified_payload": unified_payload, "orderId": order_id}
                    return await call_next(request)
                else:
                    err = result.get("error")
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "Forbidden",
                            "code": err.code if hasattr(err, 'code') else ErrorCode.invalid_receipt,
                            "message": str(err)
                        }
                    )
            except Exception as e:
                logger.error(f"⚠️ [PayNode-Middleware] Failed to process x402 v2 payload: {e}")

        # No valid payment found, return 402 with X-402-Required
        v2_response = {
            "x402Version": 2,
            "error": "Payment Required by PayNode",
            "resource": {
                "url": str(request.url),
                "description": self.description,
                "mimeType": request.headers.get("accept", "application/json")
            },
            "accepts": [
                {
                    "scheme": "exact",
                    "type": "eip3009",
                    "network": f"eip155:{self.chain_id}",
                    "amount": str(self.amount_int),
                    "asset": self.token_address,
                    "payTo": self.merchant_address,
                    "maxTimeoutSeconds": self.max_timeout_seconds,
                    "extra": {
                        "name": self.currency,
                        "version": "2"
                    }
                },
                {
                    "scheme": "exact",
                    "type": "onchain",
                    "network": f"eip155:{self.chain_id}",
                    "amount": str(self.amount_int),
                    "asset": self.token_address,
                    "payTo": self.merchant_address,
                    "maxTimeoutSeconds": self.max_timeout_seconds,
                    "router": self.contract_address
                }
            ]
        }

        b64_required = base64.b64encode(json.dumps(v2_response).encode()).decode()

        headers = {
            'X-402-Required': b64_required,
            'X-402-Order-Id': order_id,
        }
        return JSONResponse(status_code=402, headers=headers, content=v2_response)

def x402_gate(
    merchant_address: str, 
    price: str,
    **kwargs
) -> Any:
    """
    Semantic helper to mirror JS x402Gate. 
    Usage: app.add_middleware(x402_gate, merchant_address=..., price=...)
    """
    return lambda app: PayNodeMiddleware(app, merchant_address=merchant_address, price=price, **kwargs)
