# PayNode Python SDK

[![Official Documentation](https://img.shields.io/badge/Docs-docs.paynode.dev-00ff88?style=for-the-badge&logo=readthedocs)](https://docs.paynode.dev)
[![PyPI Version](https://img.shields.io/pypi/v/paynode-sdk-python.svg?style=for-the-badge)](https://pypi.org/project/paynode-sdk-python/)

The official Python SDK for the **PayNode Protocol (v2.2.1)**. PayNode allows autonomous AI Agents to seamlessly pay for APIs and computational resources using USDC on Base L2, utilizing the standardized HTTP 402 protocol with support for both on-chain receipts and off-chain signatures (EIP-3009).

## 📖 Read the Docs

**For complete installation guides, advanced usage, API references, and architecture details, please visit our official documentation:**
👉 **[docs.paynode.dev](https://docs.paynode.dev)**

## ⚡ Quick Start

### Installation

```bash
pip install paynode-sdk-python web3
```

### Agent Client (Payer)

```python
from paynode_sdk import PayNodeAgentClient

agent = PayNodeAgentClient(
    private_key="YOUR_AGENT_PRIVATE_KEY",
    rpc_urls=["https://mainnet.base.org", "https://rpc.ankr.com/base"]
)

# Automatically handles the 402 challenge, executes the Base L2 transaction, and gets the data.
response = agent.request_gate("https://api.merchant.com/premium-data", method="POST", json={"agent": "PythonAgent"})

print(response.json())
```

### Key Features (v2.2.1)
- **EIP-3009 Support**: Sign payments off-chain using `TransferWithAuthorization`, allowing for gasless or relayer-mediated settlement.
- **X402 V2 Protocol**: JSON-based handshake for more structured and machine-readable payment instructions.
- **Dual Flow**: Automatic fallback to V1 (on-chain receipts) for legacy merchant support.
- **FastAPI Middleware**: Easy-to-use middleware for merchants to protect their API routes.

## 🗺️ Roadmap
- **TRON Support**: USDT (TRC-20) payment integration.
- **Solana Support**: SPL USDC/USDT payment integration.
- **Cross-chain**: Universal settlement via bridges.

## 🚀 Run the Demo

The SDK includes a complete Merchant/Agent demo in the `examples/` directory.

### 1. Setup Environment

Copy the example environment file and fill in your keys:

```bash
cp .env.example .env
# Edit .env with your private key and RPC URLs
```

### 2. Get Test Tokens (Required for Base Sepolia)

If you're testing on Sepolia, run the helper script to mint 1,000 mock USDC:

```bash
python examples/mint_test_tokens.py
```

### 3. Run the Merchant Server (FastAPI)

```bash
python examples/fastapi_server.py
```

### 4. Run the Agent Client

In another terminal:

```bash
python examples/agent_client.py
```

The demo will perform a full loop: `402 Handshake -> On-chain Payment -> 200 Verification`.

---

## 📦 Publishing to PyPI

To publish a new version of the SDK:

1. **Install build tools**:
   ```bash
   pip install build twine
   ```
2. **Build the package**:
   ```bash
   python -m build
   ```
3. **Upload to PyPI**:
   ```bash
   python -m twine upload dist/*
   ```

---

_Built for the Autonomous AI Economy by PayNodeLabs._
