"""
PayNode Webhook Notifier — monitors on-chain PaymentReceived events
and delivers structured webhook POSTs to a merchant's endpoint.

Features:
- HMAC-SHA256 signature for authenticity (header: x-paynode-signature)
- Configurable polling interval
- Automatic retry with exponential backoff (3 attempts)
- Async-first design
"""

import json
import time
import hmac
import hashlib
import logging
import asyncio
from typing import Optional, Callable, Dict, Any, List
from web3 import Web3

from .constants import PAYNODE_ROUTER_ABI, PAYNODE_ROUTER_ADDRESS
from .errors import PayNodeException, ErrorCode

logger = logging.getLogger("paynode_sdk.webhook")


class PaymentEvent:
    """Parsed PaymentReceived event data."""

    def __init__(
        self,
        tx_hash: str,
        block_number: int,
        order_id: str,
        merchant: str,
        payer: str,
        token: str,
        amount: int,
        fee: int,
        chain_id: int,
        timestamp: float
    ):
        self.tx_hash = tx_hash
        self.block_number = block_number
        self.order_id = order_id
        self.merchant = merchant
        self.payer = payer
        self.token = token
        self.amount = amount
        self.fee = fee
        self.chain_id = chain_id
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "txHash": self.tx_hash,
            "blockNumber": self.block_number,
            "orderId": self.order_id,
            "merchant": self.merchant,
            "payer": self.payer,
            "token": self.token,
            "amount": str(self.amount),
            "fee": str(self.fee),
            "chainId": str(self.chain_id),
            "timestamp": self.timestamp,
        }


class PayNodeWebhookNotifier:
    """
    Monitors on-chain PaymentReceived events and delivers webhook notifications.

    Usage:
        notifier = PayNodeWebhookNotifier(
            rpc_url="https://mainnet.base.org",
            contract_address="0x92e20164FC457a2aC35f53D06268168e6352b200",
            webhook_url="https://myshop.com/api/paynode-webhook",
            webhook_secret="whsec_mysecretkey123",
        )
        await notifier.start()
    """

    def __init__(
        self,
        rpc_url: str,
        webhook_url: str,
        webhook_secret: str,
        contract_address: Optional[str] = None,
        chain_id: Optional[int] = None,
        poll_interval_seconds: float = 5.0,
        custom_headers: Optional[Dict[str, str]] = None,
        on_error: Optional[Callable[[Exception, PaymentEvent], None]] = None,
        on_success: Optional[Callable[[PaymentEvent], None]] = None,
    ):
        if not rpc_url:
            raise ValueError("rpc_url is required")
        if not webhook_url:
            raise ValueError("webhook_url is required")
        if not webhook_secret:
            raise ValueError("webhook_secret is required")

        self.contract_address = contract_address or PAYNODE_ROUTER_ADDRESS
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.contract_address),
            abi=PAYNODE_ROUTER_ABI
        )
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.chain_id = chain_id
        self.poll_interval = poll_interval_seconds
        self.custom_headers = custom_headers or {}
        self.on_error = on_error
        self.on_success = on_success

        self._last_block: int = 0
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def start(self, from_block: Optional[int] = None) -> None:
        """Start polling for PaymentReceived events."""
        if self._running:
            logger.warning("[PayNode Webhook] Already running.")
            return

        self._last_block = from_block if from_block is not None else self.w3.eth.block_number
        self._running = True
        logger.info(f"🔔 [PayNode Webhook] Listening from block {self._last_block} on {self.contract_address}")

        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("🔕 [PayNode Webhook] Stopped.")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                current_block = self.w3.eth.block_number
                if current_block > self._last_block:
                    events = self.contract.events.PaymentReceived().get_logs(
                        fromBlock=self._last_block + 1,
                        toBlock=current_block
                    )
                    for event in events:
                        payment = self._parse_event(event)
                        if payment:
                            await self._deliver(payment)

                    self._last_block = current_block
            except Exception as e:
                logger.error(f"[PayNode Webhook] Poll error: {e}")

            await asyncio.sleep(self.poll_interval)

    def _parse_event(self, event) -> Optional[PaymentEvent]:
        """Parse a web3 event log into a PaymentEvent."""
        try:
            args = event.args
            return PaymentEvent(
                tx_hash=event.transactionHash.hex() if hasattr(event.transactionHash, 'hex') else str(event.transactionHash),
                block_number=event.blockNumber,
                order_id=args.get("orderId", b"").hex() if isinstance(args.get("orderId"), bytes) else str(args.get("orderId", "")),
                merchant=args.get("merchant", ""),
                payer=args.get("payer", ""),
                token=args.get("token", ""),
                amount=args.get("amount", 0),
                fee=args.get("fee", 0),
                chain_id=args.get("chainId", 0),
                timestamp=time.time(),
            )
        except Exception as e:
            logger.error(f"[PayNode Webhook] Failed to parse event: {e}")
            return None

    async def _deliver(self, event: PaymentEvent, attempt: int = 1) -> None:
        """Deliver webhook POST with HMAC signature and retry logic."""
        import aiohttp  # lazy import to keep dependency optional

        MAX_RETRIES = 3

        payload = json.dumps({
            "event": "payment.received",
            "data": event.to_dict()
        })

        signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "x-paynode-signature": f"sha256={signature}",
            "x-paynode-event": "payment.received",
            "x-paynode-delivery-id": f"{event.tx_hash}-{attempt}",
            **self.custom_headers,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, data=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status >= 400:
                        raise PayNodeException(
                            ErrorCode.internal_error,
                            message=f"Webhook returned {resp.status}"
                        )

                    logger.info(f"✅ [PayNode Webhook] Delivered tx {event.tx_hash[:10]}... → {resp.status}")
                    if self.on_success:
                        self.on_success(event)

        except Exception as e:
            logger.error(f"[PayNode Webhook] Delivery failed (attempt {attempt}/{MAX_RETRIES}): {e}")

            if attempt < MAX_RETRIES:
                backoff = (2 ** attempt)  # 2s, 4s, 8s
                await asyncio.sleep(backoff)
                return await self._deliver(event, attempt + 1)

            logger.error(f"[PayNode Webhook] Gave up on tx {event.tx_hash} after {MAX_RETRIES} attempts.")
            if self.on_error:
                self.on_error(e, event)
