# PayNode SDK for AI Agents (Python/FastAPI)

High-density reference for LLMs/AI Assistants to integrate PayNode into Python APIs.

## Core Flow (402 Handshake)
Identical to the PayNode Protocol standard:
1. **Initial Call:** Client calls protected endpoint.
2. **402 Error:** Server responds 402 with `x-paynode-*` headers.
3. **Chain Pay:** Agent pays to `x-paynode-contract` using specified token/amount.
4. **Resubmit:** Client adds `x-paynode-receipt` (tx hash) to headers.

## FastAPI Snippet
```python
from fastapi import FastAPI, Request
from paynode_sdk import PayNodeMiddleware

app = FastAPI()

# Instantiate Middleware
paynode_guard = PayNodeMiddleware(
    rpc_url="https://base-sepolia.g.alchemy.com/v2/...",
    contract_address="0x...", # PayNodeRouter
    merchant_address="0x...", # Merchant Wallet
    currency="USDC",
    token_address="0x...", # USDC Contract
    price="0.05", # 0.05 USDC per call
    decimals=6,
    chain_id=84532
)

@app.middleware("http")
async def add_paynode_logic(request: Request, call_next):
    # Only protect specific routes
    if request.url.path.startswith("/api/ai"):
        return await paynode_guard(request, call_next)
    return await call_next(request)
```

## Internal Symbols
- `PayNodeVerifier`: Handles `eth_getTransactionReceipt` and event decoding.
- `ErrorCode`: Enum for all `PAYNODE_*` error strings.
- `PayNodeException`: Specific exception type for SDK errors.
