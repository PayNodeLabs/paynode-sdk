import logging
import requests
import time
from typing import Optional, Dict, Any, Union
from .utils.signature import verify_market_signature
from .middleware import PayNodeMiddleware
from .constants import PROTOCOL_VERSION

logger = logging.getLogger("paynode_sdk.merchant")

class PayNodeMerchant:
    """
    PayNodeMerchant: The high-level SDK class for Merchant Integration.
    Mirrors JS PayNodeMerchant v2.5.0 baseline.
    """
    def __init__(
        self,
        shared_secret: str,
        market_url: str = "https://mk.paynode.dev",
        quiet: bool = False
    ):
        self.shared_secret = shared_secret
        self.market_url = market_url
        self.quiet = quiet

    def sync(self, manifest: Dict[str, Any]) -> bool:
        """
        Registers or syncs the API manifest with the PayNode Market.
        This ensures the market shows the correct price and input schema.
        """
        if not self.quiet:
            logger.info(f"[PayNode-SDK] Syncing API manifest for {manifest.get('slug')} to {self.market_url}")

        try:
            payload = {**manifest, "gateway_url": manifest.get("slug")}
            response = requests.post(
                f"{self.market_url}/api/v1/merchant/apis",
                json=payload,
                timeout=10
            )
            
            result = response.json()
            if response.status_code == 200 and result.get("success"):
                if not self.quiet:
                    logger.info(f"[PayNode-SDK] Successfully synced {manifest.get('slug')}. ID: {result.get('api_id')}")
                return True
            else:
                error_msg = result.get("error") or response.reason
                if not self.quiet:
                    logger.warning(f"[PayNode-SDK] Sync failed for {manifest.get('slug')}: {error_msg}")
                return False
        except Exception as e:
            if not self.quiet:
                logger.error(f"[PayNode-SDK] Network error during sync for {manifest.get('slug')}: {e}")
            return False

    async def verify(self, request: Any) -> Dict[str, Any]:
        """
        Manual verification for FastAPI or other environments.
        Extracts headers and verifies signature. Returns the unwrapped body and context.
        """
        # Adapt for FastAPI/Starlette request or dict-like object
        if hasattr(request, "headers"):
            headers = request.headers
        else:
            headers = getattr(request, "headers", {})

        signature = headers.get("X-PayNode-Signature")
        timestamp = headers.get("X-PayNode-Timestamp")
        # Try fallbacks matching JS logic
        request_id = (
            headers.get("X-PayNode-Request-Id") or 
            headers.get("X-402-Order-Id") or 
            headers.get("PAYMENT-SIGNATURE")
        )

        is_valid = verify_market_signature(
            signature=signature,
            order_id=request_id,
            timestamp=timestamp,
            shared_secret=self.shared_secret
        )

        if not is_valid:
            return {"isValid": False, "error": "Invalid PayNode Market Signature"}

        # Handle Body Unwrap
        body = {}
        try:
            if hasattr(request, "json") and callable(request.json):
                body = await request.json()
            else:
                body = getattr(request, "body", {})
                if isinstance(body, bytes):
                    import json
                    body = json.loads(body)
        except Exception:
            pass

        paynode_context = {"orderId": request_id}

        if isinstance(body, dict) and body.get("payload") and isinstance(body.get("payload"), dict):
            # Enrich context with proxy details
            paynode_context.update({
                "txHash": headers.get("X-PayNode-Transaction-Hash") or body.get("tx_hash"),
                "amount": headers.get("X-PayNode-Amount") or body.get("amount"),
                "network": headers.get("X-PayNode-Network") or body.get("network"),
                "chainId": headers.get("X-PayNode-Chain-Id") or (str(body.get("chain_id")) if body.get("chain_id") else None),
            })
            # Transparently Unwrap Body
            body = body.get("payload")

        return {
            "isValid": True,
            "body": body,
            "paynodeContext": paynode_context
        }

    def middleware(self, merchant_address: str, price: str, manifest: Optional[Dict[str, Any]] = None, **kwargs):
        """
        Creates a unified middleware that handles:
        1. Market Proxy (Strict Signature Check + Body Unwrap)
        2. Auto-Discovery (Market Sync Probe)
        
        Usage for FastAPI:
        merchant = PayNodeMerchant(shared_secret="...")
        app.add_middleware(merchant.middleware, merchant_address="0x...", price="0.01")
        """
        from .middleware import PayNodeMerchantMiddleware
        return lambda app: PayNodeMerchantMiddleware(
            app=app,
            merchant=self,
            merchant_address=merchant_address,
            price=price,
            manifest=manifest,
            **kwargs
        )
