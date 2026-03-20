# Base Mainnet Config (Production Ready)
PAYNODE_ROUTER_ADDRESS = "0xA88B5eaD188De39c015AC51F45E1B41D3d95f2bb"
BASE_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_USDC_DECIMALS = 6

class PayNodeAgentClient:
    def __init__(self, rpc_urls: list, private_key: str, router_address: str = None):
        self.rpc_urls = rpc_urls
        self.private_key = private_key
        self.router_address = router_address or PAYNODE_ROUTER_ADDRESS
        self.current_rpc_index = 0
        
    def pay_usdc(self, merchant_address: str, amount_usdc: float):
        """
        Pay REAL USDC to a merchant on Base Mainnet.
        """
        amount_raw = int(amount_usdc * (10 ** BASE_USDC_DECIMALS))
        # Logic for transferFrom/pay would follow
        pass
