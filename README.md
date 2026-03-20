# PayNode Python SDK

为 Python 开发者提供的 PayNode 支付网关 SDK，支持 FastAPI、Flask 等主流 Web 框架。实现 M2M 场景下的 x402 握手与链上支付验证。

## 📦 安装

```bash
pip install paynode-sdk
```

## 🚀 FastAPI Middleware 初始化示例

通过注入 `PayNodeMiddleware`，您可以轻松地将任何 API 端点转变为收费接口。

```python
from fastapi import FastAPI, Request
from paynode_sdk import PayNodeMiddleware

app = FastAPI()

# 1. 初始化 PayNode 中间件
paynode = PayNodeMiddleware(
    rpc_url="https://mainnet.base.org",           # RPC 节点地址
    contract_address="0x...",                     # PayNodeRouter 合约地址
    merchant_address="0x...",                     # 商家收款钱包地址
    chain_id=8453,                                # 链 ID (Base: 8453)
    currency="USDC",                              # 计价单位
    token_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", # USDC 地址
    price="0.01",                                 # 每次调用的价格
    decimals=6                                    # 代币精度
)

# 2. 挂载中间件
@app.middleware("http")
async def paynode_gate(request: Request, call_next):
    # 此中间件会自动处理 402 握手及 x-paynode-receipt 验证
    return await paynode(request, call_next)

# 3. 受保护的路由
@app.get("/api/ai-vision")
async def ai_feature():
    return {"message": "Success! The agent has paid for this API call."}
```

## 🧪 测试与开发

SDK 采用严谨的代码审计标准，所有核心逻辑均经过多层验证。

### 运行测试

使用 `pytest` 运行测试套件。确保已配置 `PYTHONPATH` 以正确加载本地包。

```bash
# 运行所有验证逻辑测试
PYTHONPATH=. pytest tests/
```

### 开发模式

如果需要修改 `paynode_sdk` 并即时测试：

```bash
pip install -e .
```

## ⚙️ 验证逻辑详解 (Verifier)

`PayNodeVerifier` 直接通过 Web3.py 与以太坊节点交互。验证过程包括：
- **交易状态确认:** 检查交易哈希是否已上链并成功 (Status 1)。
- **合约交互验证:** 解析交易数据，确认其调用的是 `PayNodeRouter` 的 `pay` 函数。
- **金额与代币校验:** 严格匹配转账金额与指定的代币地址，防止恶意 Agent 使用虚假代币支付。
- **商户一致性:** 确认资金最终流向了预设的商户钱包。
