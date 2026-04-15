import unittest
import json
import base64
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from paynode_sdk import (
    PayNodeAgentClient, 
    PayNodeMiddleware, 
    PayNodeMerchant, 
    PayNodeMerchantMiddleware,
    PayNodePayloadHelper,
    SDK_VERSION
)

class TestSDKAlignment(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.merchant_addr = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
        self.shared_secret = "test_secret_123"
        self.api_key = "test_key"
        
    def test_version_alignment(self):
        """Ensure SDK_VERSION is 2.5.0 and globally consistent."""
        self.assertEqual(SDK_VERSION, "2.5.0")

    def test_payload_normalization(self):
        """Test PayNodePayloadHelper.normalize against X402 V2 standard format."""
        v2_payload = {
            "x402Version": 2,
            "accepted": {"scheme": "exact", "type": "onchain", "router": "0x123"},
            "payload": {"txHash": "0xabc"},
            "_paynode": {
                "sdkVersion": "2.5.0",
                "type": "onchain",
                "orderId": "req_123"
            }
        }
        b64_payload = base64.b64encode(json.dumps(v2_payload).encode()).decode()
        
        normalized = PayNodePayloadHelper.normalize(b64_payload, fallback_order_id="fallback")
        
        self.assertEqual(normalized["orderId"], "req_123")
        self.assertEqual(normalized["type"], "onchain")
        self.assertEqual(normalized["_paynode"]["sdkVersion"], "2.5.0")

    async def test_402_challenge_format(self):
        """Verify middleware includes orderId in JSON response body (v2.5.0 feature)."""
        app = FastAPI()
        app.add_middleware(
            PayNodeMiddleware, 
            merchant_address=self.merchant_addr, 
            price="0.01"
        )

        @app.get("/premium")
        async def premium():
            return {"data": "secret"}

        client = TestClient(app)
        response = client.get("/premium")
        
        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertEqual(body["x402Version"], 2)
        self.assertIn("orderId", body)
        self.assertTrue(body["orderId"].startswith("agent_py_"))

    async def test_market_proxy_hmac(self):
        """Verify PayNodeMerchant HMAC verification (aligned with JS)."""
        merchant = PayNodeMerchant(shared_secret=self.shared_secret)
        import time
        order_id = "test_order_999"
        timestamp = str(int(time.time() * 1000))
        msg = f"{order_id}:{timestamp}".encode("utf-8")
        expected_sig = hmac.new(self.shared_secret.encode(), msg, hashlib.sha256).hexdigest()
        
        # Use TestClient for consistent header behavior
        app = FastAPI()
        @app.get("/verify")
        async def verify_endpoint(request: Request):
            return await merchant.verify(request)
        
        client = TestClient(app)
        
        headers = {
            "X-PayNode-Signature": expected_sig,
            "X-PayNode-Request-Id": order_id,
            "X-PayNode-Timestamp": timestamp
        }
        
        response = client.get("/verify", headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["isValid"], result.get("error"))
        
        # Verify invalid
        response_invalid = client.get("/verify", headers={"X-PayNode-Signature": "wrong"})
        self.assertFalse(response_invalid.json()["isValid"])
        
        # Verify drift
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        headers_old = {**headers, "X-PayNode-Timestamp": old_ts}
        response_old = client.get("/verify", headers=headers_old)
        self.assertFalse(response_old.json()["isValid"])

    async def test_merchant_middleware_discovery(self):
        """Test PayNodeMerchantMiddleware discovery probe."""
        merchant = PayNodeMerchant(shared_secret=self.shared_secret)
        app = FastAPI()
        manifest = {"name": "Test Tool", "price": "0.1"}
        app.add_middleware(
            PayNodeMerchantMiddleware,
            merchant=merchant,
            merchant_address=self.merchant_addr,
            price="0.1",
            manifest=manifest
        )

        @app.post("/tool")
        async def tool():
            return {"ok": True}

        client = TestClient(app)
        
        # Signed Discovery Probe
        order_id = "probe_1"
        import time
        timestamp = str(int(time.time() * 1000))
        msg = f"{order_id}:{timestamp}".encode("utf-8")
        sig = hmac.new(self.shared_secret.encode(), msg, hashlib.sha256).hexdigest()
        
        headers = {
            "X-PayNode-Signature": sig,
            "X-PayNode-Timestamp": timestamp,
            "X-PayNode-Request-Id": order_id,
            "X-PayNode-Discovery": "true"
        }
        
        response = client.post("/tool", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "DISCOVERED")
        self.assertEqual(data["manifest"]["name"], "Test Tool")

    async def test_merchant_middleware_unwrap(self):
        """Test PayNodeMerchantMiddleware body unwrapping."""
        merchant = PayNodeMerchant(shared_secret=self.shared_secret)
        app = FastAPI()
        app.add_middleware(
            PayNodeMerchantMiddleware,
            merchant=merchant,
            merchant_address=self.merchant_addr,
            price="0.1"
        )

        from fastapi import Request
        @app.post("/tool")
        async def tool(request: Request):
            # Access unwrapped body from state
            return {"echo": request.state.paynode_body}

        client = TestClient(app)
        
        order_id = "req_unwrap"
        import time
        timestamp = str(int(time.time() * 1000))
        sig = hmac.new(self.shared_secret.encode(), f"{order_id}:{timestamp}".encode(), hashlib.sha256).hexdigest()
        
        # Wrapped payload
        wrapped_body = {
            "payload": {"query": "hello world"},
            "tx_hash": "0x123",
            "amount": "100000"
        }
        
        headers = {
            "X-PayNode-Signature": sig,
            "X-PayNode-Timestamp": timestamp,
            "X-PayNode-Request-Id": order_id
        }
        
        response = client.post("/tool", headers=headers, json=wrapped_body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["echo"]["query"], "hello world")

if __name__ == "__main__":
    unittest.main()
