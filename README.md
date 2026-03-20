# PayNode Python SDK

[![Official Documentation](https://img.shields.io/badge/Docs-docs.paynode.dev-00ff88?style=for-the-badge&logo=readthedocs)](https://docs.paynode.dev)
[![PyPI Version](https://img.shields.io/pypi/v/paynode-sdk-python.svg?style=for-the-badge)](https://pypi.org/project/paynode-sdk-python/)

The official Python SDK for the **PayNode Protocol**. PayNode allows autonomous AI Agents to seamlessly pay for APIs and computational resources using USDC on Base L2, utilizing the standardized HTTP 402 protocol.

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
from paynode_sdk import Client

agent = Client(private_key="YOUR_AGENT_PRIVATE_KEY")

# Automatically handles the 402 challenge, executes the Base L2 transaction, and gets the data.
response = agent.get("https://api.merchant.com/premium-data")

print(response.json())
```

### Merchant Middleware (FastAPI Receiver)

```python
from fastapi import FastAPI, Depends
from paynode_sdk.middleware import PayNodeMiddleware

app = FastAPI()

# Protect routes with a 1.50 USDC fee requirement
require_payment = PayNodeMiddleware(
    price=1.50, 
    merchant_wallet="0xYourWalletAddress..."
)

@app.get("/premium-data", dependencies=[Depends(require_payment)])
def get_premium_data():
    return {"secret": "This is paid M2M data."}
```

---
*Built for the Autonomous AI Economy by PayNodeLabs.*