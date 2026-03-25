import uvicorn
import os
from fastapi import FastAPI, Request
from paynode_sdk import (
    PayNodeMiddleware, 
    PAYNODE_ROUTER_ADDRESS_SANDBOX, 
    BASE_USDC_ADDRESS_SANDBOX
)
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="PayNode Python Merchant Demo")

# 🚀 PayNode Python Merchant Demo (FastAPI)
# 
# Minimal configuration using defaults for Base Mainnet:
# app.add_middleware(PayNodeMiddleware, merchant_address='0x...', price='1.00')

app.add_middleware(
    PayNodeMiddleware,
    merchant_address=os.getenv("MERCHANT_ADDRESS", "0xYourMerchantWalletAddress"), 
    price="0.10",
    # Overriding defaults for Sandbox (Sepolia)
    chain_id=84532,
    contract_address=PAYNODE_ROUTER_ADDRESS_SANDBOX,
    token_address=BASE_USDC_ADDRESS_SANDBOX,
)

@app.get("/api/premium-python-data")
async def get_premium_data(request: Request):
    """
    If this route is reached, it means the middleware has already 
    verified the on-chain payment.
    """
    paynode_state = request.state.paynode
    unified_payload = paynode_state.get("unified_payload", {})
    order_id = paynode_state.get("order_id")
    
    tx_hash = unified_payload.get("payload", {}).get("txHash") or unified_payload.get("payload", {}).get("signature", "unknown")
    payment_type = unified_payload.get("type", "unknown")
    
    print(f"✅ [Py-PayNode] Payment Verified. Tx: {tx_hash}, Order: {order_id}, Type: {payment_type}")
    
    return {
        "status": "success",
        "data": {
            "message": "Premium content served by PayNode-Python SDK.",
            "secret_code": "AGENTIC_BASE_SUMMIT_2026",
            "timestamp": "2026-03-22T19:41:09+08:00"
        },
        "payment_info": {
            "receipt": tx_hash,
            "order_id": order_id,
            "payment_type": payment_type
        }
    }

if __name__ == "__main__":
    print("🚀 PayNode Python Server starting on http://localhost:8000")
    print("🔒 Protected Endpoint: http://localhost:8000/api/premium-python-data")
    uvicorn.run(app, host="0.0.0.0", port=8000)
