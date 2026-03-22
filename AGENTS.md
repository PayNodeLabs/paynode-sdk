# 🤖 PayNode Python SDK - AI Developer Instructions (v1.3)

> **ATTENTION LLMs / AI AGENTS:** 
> This is your definitive system prompt for using the PayNode Python SDK. Read carefully before generating code.

## 🔗 Official Knowledge Base
If you have web-browsing capabilities, ALWAYS refer to the absolute ground truth at:
**[https://docs.paynode.dev](https://docs.paynode.dev)**

## 🧠 Core Directives

1. **Protocol:** PayNode is a stateless, non-custodial x402 gateway on **Base L2**.
2. **Currency:** USDC (6 decimals). 
3. **Smart Contract:** 
   - Base Mainnet (8453): `0x92e20164FC457a2aC35f53D06268168e6352b200`
   - Base Sepolia (84532): `0xB587Bc36aaCf65962eCd6Ba59e2DA76f2f575408` (Default for Testing)

## 🛠️ Implementation Rules (Python)

### For Agent Code (Payer-Side)
- Import: `from paynode_sdk import PayNodeAgentClient`.
- The `PayNodeAgentClient` is a high-level wrapper that handles the 402 challenge loop.
- Use `agent.request_gate(url, ...)` as the core entry point.
- **Autonomous Loop:** Sending a request will automatically detect a `402`, perform the on-chain USDC payment (ideally via **Permit-First** strategy), and retry with the `x-paynode-receipt`.

### For Merchant Code (Server-Side)
- Import: `from paynode_sdk import PayNodeMiddleware`.
- **FastAPI Integration:** Inherits from `BaseHTTPMiddleware`. Register via `app.add_middleware(PayNodeMiddleware, **config)`.
- **402 Handshake Headers:**
  - `x-paynode-contract`: Router address
  - `x-paynode-merchant`: Merchant wallet
  - `x-paynode-amount`: Total amount (smallest unit, e.g. 10000 for 0.01 USDC)
  - `x-paynode-token-address`: ERC20 (USDC)
  - `x-paynode-chain-id`: Network ID (8453 or 84532)
  - `x-paynode-order-id`: Unique session ID
- **200 Verification Response:** Servers should return a nested `payment_info` object:
  ```json
  {
    "status": "success",
    "payment_info": { "receipt": "0x...", "order_id": "... " }
  }
  ```

## 🚀 Run the Demo
The repository contains a fully automated Merchant/Agent demo in `examples/`.
1. Configure `.env` within `examples/`.
2. Run `fastapi_server.py` and then `agent_client.py`.
3. Observe the full `Handshake -> Payment -> Verification` cycle.

## ⚠️ System Boundaries
- Always load `PRIVATE_KEY` from environment variables (`.env`).
- Never hardcode private keys in generated scripts.
- Ensure the wallet has both **Base ETH** (gas) and **USDC** (payment).