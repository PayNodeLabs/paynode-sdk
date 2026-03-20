import requests
import time
from web3 import Web3
from .constants import PAYNODE_ROUTER_ADDRESS, BASE_USDC_ADDRESS, BASE_USDC_DECIMALS

class PayNodeAgentClient:
    def __init__(self, rpc_urls: list, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_urls[0]))
        self.account = self.w3.eth.account.from_key(private_key)
        self.private_key = private_key

    def get(self, url, **kwargs):
        response = requests.get(url, **kwargs)
        if response.status_code == 402:
            print("💡 [PayNode-PY] 402 Detected. Handling payment...")
            return self._handle_402(url, "GET", response.headers, **kwargs)
        return response

    def post(self, url, **kwargs):
        response = requests.post(url, **kwargs)
        if response.status_code == 402:
            print("💡 [PayNode-PY] 402 Detected. Handling payment...")
            return self._handle_402(url, "POST", response.headers, **kwargs)
        return response

    def _handle_402(self, url, method, headers, **kwargs):
        router_addr = headers.get('x-paynode-contract')
        merchant_addr = headers.get('x-paynode-merchant')
        amount_raw = int(headers.get('x-paynode-amount', 0))
        token_addr = headers.get('x-paynode-token-address')
        order_id = headers.get('x-paynode-order-id')

        # 1. Handle Approval
        self._ensure_allowance(token_addr, router_addr, amount_raw)

        # 2. Execute Payment
        tx_hash = self._execute_pay(router_addr, token_addr, merchant_addr, amount_raw, order_id)
        print(f"✅ [PayNode-PY] Payment successful: {tx_hash}")

        # 3. Retry
        retry_headers = kwargs.get('headers', {}).copy()
        retry_headers.update({
            'x-paynode-receipt': tx_hash,
            'x-paynode-order-id': order_id
        })
        kwargs['headers'] = retry_headers
        
        if method == "GET":
            return requests.get(url, **kwargs)
        return requests.post(url, **kwargs)

    def _ensure_allowance(self, token_addr, spender_addr, amount):
        token_abi = [
            {"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            {"constant": False, "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
        ]
        token = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=token_abi)
        allowance = token.functions.allowance(self.account.address, Web3.to_checksum_address(spender_addr)).call()
        
        if allowance < amount:
            print(f"🔐 [PayNode-PY] Allowance too low. Granting Infinite Approval...")
            # Use 20% higher gas price for better reliability
            current_gas_price = int(self.w3.eth.gas_price * 1.2)
            
            tx = token.functions.approve(Web3.to_checksum_address(spender_addr), 2**256 - 1).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address, 'pending'),
                'gas': 100000,
                'gasPrice': current_gas_price
            })
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            print(f"⏳ Waiting for approval confirmation: {self.w3.to_hex(tx_h)}...")
            self.w3.eth.wait_for_transaction_receipt(tx_h)
            time.sleep(1) # Extra buffer for indexers

    def _execute_pay(self, router_addr, token_addr, merchant_addr, amount, order_id):
        router_abi = [{"inputs": [{"name": "t", "type": "address"}, {"name": "m", "type": "address"}, {"name": "a", "type": "uint256"}, {"name": "o", "type": "bytes32"}], "name": "pay", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=router_abi)
        order_id_bytes = self.w3.keccak(text=order_id)

        # Use 20% higher gas price
        current_gas_price = int(self.w3.eth.gas_price * 1.2)

        tx = router.functions.pay(
            Web3.to_checksum_address(token_addr),
            Web3.to_checksum_address(merchant_addr),
            amount,
            order_id_bytes
        ).build_transaction({
            'from': self.account.address,
            'nonce': self.w3.eth.get_transaction_count(self.account.address, 'pending'),
            'gas': 200000,
            'gasPrice': current_gas_price
        })
        signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_h)
        return self.w3.to_hex(tx_h)
