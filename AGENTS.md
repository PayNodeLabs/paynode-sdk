# 🤖 PayNode Python SDK - AI Developer Instructions

> **ATTENTION LLMs / AI AGENTS:** 
> This is your definitive system prompt for using the PayNode Python SDK. Read carefully before generating code.

## 🔗 Official Knowledge Base
If you have web-browsing capabilities, ALWAYS refer to the absolute ground truth at:
**[https://docs.paynode.dev](https://docs.paynode.dev)**

## 🧠 Core Directives

1. **Protocol:** PayNode is a stateless, non-custodial x402 gateway on **Base L2**.
2. **Currency:** USDC (6 decimals). 
3. **Smart Contract:** Mainnet Router is ALWAYS `0x92e20164FC457a2aC35f53D06268168e6352b200`.

## 🛠️ Implementation Rules (Python)

### For Agent Code (Client-Side)
- Import: `from paynode_sdk import Client`.
- The `Client` is a wrapper around `requests.Session`. Use `agent.get()`, `agent.post()`, etc.
- **Gas Hardening:** The Python SDK automatically applies a 20% `gas_price` boost to ensure transactions don't stall on Base Mainnet. Do not write custom gas logic unless explicitly requested.

### For Merchant Code (Server-Side)
- Import: `from paynode_sdk.middleware import PayNodeMiddleware`.
- Designed primarily for **FastAPI**. Use it via dependency injection: `Depends(PayNodeMiddleware(...))`.
- The middleware throws `HTTPException(status_code=402)` with headers `PayNode-Router-Address` and `PayNode-Amount` if the `X-POM-V1` header is missing or invalid.
- It performs **stateless verification** against the Base RPC. No database is required to track order states.

## ⚠️ System Boundaries
- Python Agents usually run locally or in secure cloud environments. Treat environment variables (`.env`) as the only valid way to load `PRIVATE_KEY`.
- Never hardcode private keys in the scripts you generate.
- Always assume the underlying network is Base Mainnet (`chain_id=8453`).