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
from paynode_sdk import PayNodeAgentClient

agent = PayNodeAgentClient(private_key="YOUR_AGENT_PRIVATE_KEY", rpc_url="https://mainnet.base.org")

# Automatically handles the 402 challenge, executes the Base L2 transaction, and gets the data.
response = agent.request_gate("https://api.merchant.com/premium-data", method="POST", json={"agent": "PythonAgent"})

print(response.json())
```

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
*Built for the Autonomous AI Economy by PayNodeLabs.*
