import uvicorn
import os
from fastapi import FastAPI, Request
from paynode_sdk import PayNodeMiddleware # This correctly references local source
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="PayNode Python Merchant Demo")

# PayNode Python Merchant Demo (FastAPI)
#
# To run:
# 1. Install deps: pip install fastapi uvicorn python-dotenv paynode-sdk-python
# 2. Setup your .env file (based on .env.example)
# 3. Run: python examples/fastapi_server.py

# Configuration (Base Sepolia)
PAYNODE_CONFIG = {
    "rpc_url": os.getenv("PAYNODE_RPC_URL", "https://sepolia.base.org"),
    "contract_address": os.getenv("PAYNODE_CONTRACT_ADDRESS", "0xB587Bc36aaCf65962eCd6Ba59e2DA76f2f575408"), # PayNode Router
    "merchant_address": os.getenv("MERCHANT_ADDRESS", "0xYourMerchantWalletAddress"), 
    "chain_id": int(os.getenv("CHAIN_ID", 84532)),
    "currency": os.getenv("CURRENCY", "USDC"),
    "token_address": os.getenv("MERCHANT_TOKEN_ADDRESS", "0xYourDeployedTokenAddress"), 
    "price": os.getenv("PRICE", "0.01"),
    "decimals": int(os.getenv("TOKEN_DECIMALS", 6)),
}

# Apply the Middleware globally or to specific routers
# This middleware also handles:
# 1. Inspecting headers for 'x-paynode-receipt' (txHash)
# 2. On-chain verification for correct merchant, amount, token, and chainId
# 3. Idempotency check (preventing same txHash from double-spending access)
app.add_middleware(PayNodeMiddleware, **PAYNODE_CONFIG)

@app.get("/api/premium-python-data")
async def get_premium_data(request: Request):
    """
    If this route is reached, it means the middleware has already 
    verified the on-chain payment.
    """
    receipt = request.headers.get('x-paynode-receipt')
    order_id = request.headers.get('x-paynode-order-id')
    
    print(f"✅ [Py-PayNode] Payment Verified. Tx: {receipt}, Order: {order_id}")
    
    return {
        "status": "success",
        "data": {
            "message": "Premium content served by PayNode-Python SDK.",
            "secret_code": "AGENTIC_BASE_SUMMIT_2026",
            "timestamp": "2026-03-22T19:41:09+08:00" # Placeholder or dynamic
        },
        "payment_info": {
            "receipt": receipt,
            "order_id": order_id
        }
    }

if __name__ == "__main__":
    print("🚀 PayNode Python Server starting on http://localhost:8000")
    print("🔒 Protected Endpoint: http://localhost:8000/api/premium-python-data")
    uvicorn.run(app, host="0.0.0.0", port=8000)
