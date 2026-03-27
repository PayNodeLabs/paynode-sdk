# 🤖 PayNode Python SDK - AI Developer Instructions (v2.2.0)

> **ATTENTION LLMs / AI AGENTS:**
> This is your definitive system prompt for using the PayNode Python SDK. Read carefully before generating code.

## 🔗 Official Knowledge Base
If you have web-browsing capabilities, ALWAYS refer to the absolute ground truth at:
**[https://docs.paynode.dev](https://docs.paynode.dev)**

## 🧠 Core Directives

1. **Protocol:** PayNode is a stateless, non-custodial x402 gateway on **Base L2**.
2. **X402 V2 Support:** Supports both V1 (On-chain Receipt) and V2 (Off-chain Signature/JSON) handshake protocols.
3. **Currency:** USDC (6 decimals).
4. **Smart Contract:**
   - Base Mainnet (8453): `0x4A73696ccF76E7381b044cB95127B3784369Ed63`
   - Base Sepolia (84532): `0x24cD8b68aaC209217ff5a6ef1Bf55a59f2c8Ca6F` (Default for Testing)

## 🏗️ File Structure
- `paynode_sdk/client.py`: `PayNodeAgentClient` for autonomous 402 loops (V1 & V2).
- `paynode_sdk/middleware.py`: FastAPI/Starlette `PayNodeMiddleware`.
- `paynode_sdk/constants.py`: Protocol constants (sync via `scripts/sync-config.py`).
- `paynode_sdk/errors.py`: Custom exceptions and protocol error codes.
- `paynode_sdk/verifier.py`: On-chain and Off-chain (EIP-3009) verification logic.
- `examples/`: Reference implementations for Agent and Merchant flows.

## 🛠️ Implementation Rules (Python)

### For Agent Code (Payer-Side)
- Import: `from paynode_sdk import PayNodeAgentClient`.
- Use `agent.request_gate(url, ...)` as the core entry point.
- **Autonomous Loop:** Automatically detects `402`, performs USDC payment (EIP-2612 Permit or EIP-3009 Authorization), and retries.
- Always provide `rpc_urls` as a list for failover support.

### For Merchant Code (Server-Side)
- **FastAPI Integration:** `app.add_middleware(PayNodeMiddleware, **config)`.
- **Handshake Headers:** `x-paynode-contract`, `x-paynode-merchant`, `x-paynode-amount` (min 1000), `x-paynode-chain-id`.
- **Response Format:** Return `payment_info` object with `receipt` and `order_id` on success.

## 🧪 Test & Build Patterns
- **Testing:** Use `pytest`. Test files located in `tests/`.
- **Command:** `PYTHONPATH=. pytest tests/`
- **Build:** `python -m build` for distribution.
- **Linting:** Follow PEP 8. Use `black` or `ruff` if available.

## 🚫 Python/Web3.py Anti-Patterns
- **No Sync in Async:** Don't use blocking `requests` inside async FastAPI routes. Use `httpx`.
- **Checksum Addresses:** Always use `Web3.to_checksum_address()`.
- **Decimal Precision:** Never use floats for USDC. Use integers (smallest unit).
- **Gas Handling:** Don't hardcode `gasPrice`. Use `web3.eth.generate_gas_price()` or 1.2x multiplier.
- **Event Polling:** Avoid tight loops for transaction receipts. Use `web3.eth.wait_for_transaction_receipt`.

## 🚀 Run the Demo
1. Configure `.env` in `examples/`.
2. Run `fastapi_server.py` then `agent_client.py`.
3. Check `mint_test_tokens.py` for Sepolia USDC setup.

## ⚠️ System Boundaries
- Load `PRIVATE_KEY` via `os.getenv()`. Never hardcode.
- Verify wallet has **Base ETH** for gas and **USDC** for payments.
- Protocol minimum payment is 1000 units (0.001 USDC).
