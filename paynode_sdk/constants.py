PAYNODE_ROUTER_ADDRESS = "0xA88B5eaD188De39c015AC51F45E1B41D3d95f2bb"
PAYNODE_ROUTER_ADDRESS_SANDBOX = "0x1E12700393D3222BC451fb0aEe7351E4eB6779b1"
BASE_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_USDC_ADDRESS_SANDBOX = "0xeAC1f2C7099CdaFfB91Aa3b8Ffd653Ef16935798"
BASE_USDC_DECIMALS = 6

# Accepted token addresses per chain (anti-fake-token whitelist)
ACCEPTED_TOKENS = {
    # Base Mainnet (chainId: 8453)
    8453: [
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
        "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",  # USDT
    ],
    # Base Sepolia (chainId: 84532)
    84532: [
        "0xeAC1f2C7099CdaFfB91Aa3b8Ffd653Ef16935798",  # USDC (Sandbox)
    ],
}

PAYNODE_ROUTER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "orderId", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "merchant", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "payer", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "fee", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "chainId", "type": "uint256"}
        ],
        "name": "PaymentReceived",
        "type": "event"
    }
]
