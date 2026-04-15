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
    BASE_USDC_DECIMALS,
    PROTOCOL_VERSION,
    SDK_VERSION
)
from datetime import datetime, timezone
from typing import Optional, Callable, Any, Dict
from .utils.payload import PayNodePayloadHelper

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
        v2_payload_header = request.headers.get('PAYMENT-SIGNATURE') or request.headers.get('X-402-Payload')
        order_id = request.headers.get('X-402-Order-Id')

        if not order_id:
            order_id = (self.generate_order_id)(request)

        # Handle x402 v2 Unified Payload
        unified_payload = None
        if v2_payload_header:
            try:
                unified_payload = PayNodePayloadHelper.normalize(v2_payload_header, order_id)
                order_id = unified_payload.get("orderId") or order_id
            except Exception as e:
                logger.error(f"❌ [PayNode-Middleware] Failed to decode payment payload header: {e}")

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
                    
                    # Construct settlement response header
                    settle_response = {
                        "success": True,
                        "transaction": unified_payload.get("payload", {}).get("txHash") or "",
                        "network": f"eip155:{self.chain_id}",
                        "payer": result.get("payer", "")
                    }
                    b64_settle = base64.b64encode(json.dumps(settle_response).encode()).decode()
                    
                    response = await call_next(request)
                    response.headers["PAYMENT-RESPONSE"] = b64_settle
                    response.headers["X-PAYMENT-RESPONSE"] = b64_settle # Compatibility
                    return response
                else:
                    err = result.get("error")
                    error_code = err.code if hasattr(err, 'code') else ErrorCode.invalid_receipt
                    
                    # Also include PAYMENT-RESPONSE header on failure for protocol symmetry
                    settle_fail = {
                        "success": False,
                        "errorReason": error_code,
                        "transaction": "",
                        "network": f"eip155:{self.chain_id}"
                    }
                    b64_settle_fail = base64.b64encode(json.dumps(settle_fail).encode()).decode()
                    
                    headers = {
                        "PAYMENT-RESPONSE": b64_settle_fail,
                        "X-PAYMENT-RESPONSE": b64_settle_fail
                    }
                    return JSONResponse(
                        status_code=403,
                        headers=headers,
                        content={
                            "error": "Forbidden",
                            "code": error_code,
                            "message": str(err)
                        }
                    )
            except Exception as e:
                logger.error(f"⚠️ [PayNode-Middleware] Failed to process x402 v2 payload: {e}")

        # No valid payment found, return 402 with X-402-Required
        v2_response = {
            "x402Version": 2,
            "error": "Payment Required by PayNode",
            "orderId": order_id,
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
            'PAYMENT-REQUIRED': b64_required,
            'X-402-Required': b64_required,
            'X-402-Order-Id': order_id,
        }
        return JSONResponse(status_code=402, headers=headers, content=v2_response)


class PayNodeMerchantMiddleware(BaseHTTPMiddleware):
    """
    Unified PayNode Merchant Middleware
    Handles: 
    1. Market Proxy (Strict HMAC Signature + Body Unwrapping)
    2. Discovery Probes (Auto-respond with API Manifest)
    
    Note: Standalone direct X402 payment flow should be handled 
    via x402_gate.
    """
    def __init__(
        self,
        app: Any,
        merchant: Any,  # PayNodeMerchant instance
        merchant_address: str,
        price: str,
        manifest: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(app)
        self.merchant = merchant
        self.merchant_address = merchant_address
        self.price = price
        self.manifest = manifest or {}
        self.quiet = getattr(merchant, "quiet", False)

    async def dispatch(self, request: Request, call_next):
        # 1. Check for Market Proxy Headers
        headers = request.headers
        signature = headers.get("X-PayNode-Signature")
        timestamp = headers.get("X-PayNode-Timestamp")
        request_id = headers.get("X-PayNode-Request-Id") or headers.get("X-402-Order-Id")
        is_discovery = headers.get("X-PayNode-Discovery") == "true"

        if signature and request_id and timestamp:
            # ✅ Verify Signature from PayNode Market
            from .utils.signature import verify_market_signature
            is_valid = verify_market_signature(
                signature=signature,
                order_id=request_id,
                timestamp=timestamp,
                shared_secret=self.merchant.shared_secret
            )

            if not is_valid:
                if not self.quiet:
                    logger.error(f"[PayNode-SDK] Invalid Market Proxy Signature for request {request_id}")
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "PayNode Market Signature verification failed."}
                )

            # --- Scene A: Discovery Probe ---
            if is_discovery:
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "DISCOVERED",
                        "x402Version": PROTOCOL_VERSION,
                        "manifest": self.manifest,
                        "last_synced": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    }
                )

            # --- Scene B: Proxy Flow - Context Enrichment ---
            # In FastAPI, we store the unwrapped data in request.state
            # Transparently unwrapping req.body is complex in BaseHTTPMiddleware, 
            # so we provide the unwrapped body in request.state.paynode_body
            
            paynode_context = {"orderId": request_id}
            
            # Simple body check (may consume stream, so we use request.state to cache if needed)
            # For now, we mirror JS context enrichment
            try:
                # We assume the Market Proxy always sends JSON
                body = await request.json()
                if isinstance(body, dict) and body.get("payload"):
                    metadata = {k: v for k, v in body.items() if k != "payload"}
                    
                    request.state.paynode = {
                        "orderId": request_id,
                        "txHash": headers.get("X-PayNode-Transaction-Hash") or body.get("tx_hash"),
                        "amount": headers.get("X-PayNode-Amount") or body.get("amount"),
                        "network": headers.get("X-PayNode-Network") or body.get("network"),
                        "chainId": headers.get("X-PayNode-Chain-Id") or (str(body.get("chain_id")) if body.get("chain_id") else None),
                        "proxyMetadata": metadata
                    }
                    # Store the unwrapped body for the handler
                    request.state.paynode_body = body.get("payload")
                    
                    # NOTE: To truly "unwrap" req.body for downstream handlers (so request.json() works),
                    # we would need to override the request.receive channel. 
                    # For this SDK, we recommend handlers check request.state.paynode_body if accessed via Proxy.
                else:
                    request.state.paynode = {"orderId": request_id}
                    request.state.paynode_body = body
            except Exception:
                request.state.paynode = {"orderId": request_id}
                request.state.paynode_body = None

            return await call_next(request)

        # 2. Scene C: Direct Agent Call (Rejected)
        # PayNodeMerchant requires Market Proxy for verification.
        return JSONResponse(
            status_code=403,
            content={
                "error": "forbidden",
                "message": "PayNode Market Auth required. This API must be accessed via PayNode Market Proxy for verification."
            }
        )

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
