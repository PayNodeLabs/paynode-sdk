import time
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
        generate_order_id: Optional[Callable[[Request], str]] = None
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

        # Calculate raw amount (integer)
        self.amount_int = int(float(price) * (10 ** decimals))

    async def dispatch(self, request: Request, call_next):
        receipt_hash = request.headers.get('x-paynode-receipt')
        order_id = request.headers.get('x-paynode-order-id')

        if not order_id:
            order_id = self.generate_order_id(request)

        # Phase 1: Handshake (402 Payment Required)
        if not receipt_hash:
            headers = {
                'x-paynode-contract': self.contract_address,
                'x-paynode-merchant': self.merchant_address,
                'x-paynode-amount': str(self.amount_int),
                'x-paynode-currency': self.currency,
                'x-paynode-token-address': self.token_address,
                'x-paynode-chain-id': str(self.chain_id),
                'x-paynode-order-id': order_id,
            }
            return JSONResponse(
                status_code=402,
                headers=headers,
                content={
                    "error": "Payment Required",
                    "code": ErrorCode.missing_receipt,
                    "message": "Please pay to PayNode contract and provide 'x-paynode-receipt' header.",
                    "amount": self.price,
                    "currency": self.currency
                }
            )

        # Phase 2: On-chain Verification
        result = await self.verifier.verify_payment(receipt_hash, {
            "merchantAddress": self.merchant_address,
            "tokenAddress": self.token_address,
            "amount": self.amount_int,
            "orderId": order_id
        })

        if result.get("isValid"):
            # Validation Passed!
            return await call_next(request)
        else:
            # Validation Failed
            err = result.get("error")
            print(f"❌ [PayNode-PY] Verification Failed for Order: {order_id}. Reason: {str(err)}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "code": err.code if hasattr(err, 'code') else ErrorCode.invalid_receipt,
                    "message": str(err)
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
