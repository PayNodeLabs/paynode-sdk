import time
import logging
import threading
import requests
from eth_account.messages import encode_typed_data
from web3 import Web3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .constants import PAYNODE_ROUTER_ADDRESS, BASE_USDC_ADDRESS, BASE_USDC_DECIMALS, BASE_RPC_URLS
from .errors import PayNodeException, ErrorCode

logger = logging.getLogger("paynode_sdk.client")

class PayNodeAgentClient:
    """
    The main PayNode Client for AI Agents (v1.1.1).
    Automatically handles the x402 'Payment Required' handshake.
    Supports RPC redundancy and EIP-2612 Permit-First payments.
    """
    def __init__(self, private_key: str, rpc_urls: list | str = BASE_RPC_URLS):
        self.rpc_urls = rpc_urls if isinstance(rpc_urls, list) else [rpc_urls]
        self.w3 = self._init_w3()
        
        # Initialize account and discard private key string
        self.account = self.w3.eth.account.from_key(private_key)
        self.nonce_lock = threading.Lock()
        
        # Setup session
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _init_w3(self):
        """Finds a working RPC from the list."""
        for rpc in self.rpc_urls:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 5}))
                if w3.is_connected():
                    return w3
            except Exception as e:
                logger.warning(f"⚠️ [PayNode-PY] RPC {rpc} failed: {str(e)}")
                continue
        raise PayNodeException("Failed to connect to any provided RPC nodes.", ErrorCode.rpc_error)

    def request_gate(self, url: str, method: str = "GET", **kwargs):
        """The high-level autonomous method handling 402 loop."""
        return self._request_with_402_retry(method.upper(), url, **kwargs)

    def get(self, url, **kwargs):
        return self.request_gate(url, "GET", **kwargs)

    def post(self, url, **kwargs):
        return self.request_gate(url, "POST", **kwargs)

    def _request_with_402_retry(self, method, url, max_retries=3, **kwargs):
        for _ in range(max_retries):
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 402:
                logger.info("💡 [PayNode-PY] 402 Detected. Handling payment...")
                try:
                    kwargs = self._handle_402(response.headers, **kwargs)
                except Exception as e:
                    if isinstance(e, PayNodeException): raise
                    raise PayNodeException(f"An unexpected error occurred: {str(e)}", ErrorCode.internal_error)
                continue
            return response
        return response

    def _handle_402(self, headers, **kwargs):
        router_addr = headers.get('x-paynode-contract')
        merchant_addr = headers.get('x-paynode-merchant')
        amount_raw = int(headers.get('x-paynode-amount', 0))
        token_addr = headers.get('x-paynode-token-address')
        order_id = headers.get('x-paynode-order-id')
        currency = headers.get('x-paynode-currency', 'USDC')
        chain_id_header = headers.get('x-paynode-chain-id')

        if not all([router_addr, merchant_addr, amount_raw, token_addr, order_id]):
            raise PayNodeException("Malformed 402 headers: missing metadata", ErrorCode.internal_error)

        # Network safety check (v1.4)
        if chain_id_header:
            current_chain_id = self.w3.eth.chain_id
            if int(chain_id_header) != current_chain_id:
                raise PayNodeException(f"Network mismatch: Current {current_chain_id}, Request {chain_id_header}.", ErrorCode.invalid_receipt)

        logger.info(f"💡 [PayNode-PY] Payment request: {amount_raw} {currency} to {merchant_addr}")

        # v1.3 Constraint: Min payment protection
        if amount_raw < 1000:
            raise PayNodeException("Payment amount is below the protocol minimum (1000).", ErrorCode.amount_too_low)

        # Protocol v1.3: Permit-First Execution
        try:
            # Check allowance first to decide if we need Permit
            allowance = self._get_allowance(token_addr, router_addr)
            if allowance >= amount_raw:
                tx_hash = self._execute_pay(router_addr, token_addr, merchant_addr, amount_raw, order_id)
            else:
                logger.info("⚡ [PayNode-PY] Insufficient allowance. Attempting Permit-First payment...")
                tx_hash = self.pay_with_permit(router_addr, token_addr, merchant_addr, amount_raw, order_id)
            
            logger.info(f"✅ [PayNode-PY] Payment successful: {tx_hash}")
        except Exception as e:
            if isinstance(e, PayNodeException): raise
            raise PayNodeException(f"On-chain transaction reverted or failed: {str(e)}", ErrorCode.transaction_failed)

        retry_headers = kwargs.get('headers', {}).copy()
        retry_headers.update({'x-paynode-receipt': tx_hash, 'x-paynode-order-id': order_id})
        kwargs['headers'] = retry_headers
        return kwargs

    def _get_allowance(self, token_addr, spender_addr):
        abi = [{"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]
        token = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=abi)
        return token.functions.allowance(self.account.address, Web3.to_checksum_address(spender_addr)).call()

    def sign_permit(self, token_addr, spender_addr, amount, deadline=None):
        """Signs EIP-2612 Permit data."""
        if deadline is None:
            deadline = int(time.time()) + 3600
        
        token_addr = Web3.to_checksum_address(token_addr)
        spender_addr = Web3.to_checksum_address(spender_addr)
        
        # Get nonce and domain separator
        abi = [
            {"inputs": [{"name": "o", "type": "address"}], "name": "nonces", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
            {"inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"}
        ]
        token = self.w3.eth.contract(address=token_addr, abi=abi)
        nonce = token.functions.nonces(self.account.address).call()
        name = token.functions.name().call()
        chain_id = self.w3.eth.chain_id

        domain = {
            "name": name,
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": token_addr,
        }
        message = {
            "owner": self.account.address,
            "spender": spender_addr,
            "value": amount,
            "nonce": nonce,
            "deadline": deadline,
        }
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Permit": [
                {"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        }
        
        structured_data = {
            "types": types,
            "domain": domain,
            "primaryType": "Permit",
            "message": message,
        }
        
        signed = self.account.sign_typed_data(full_message=structured_data)
        return {
            "v": signed.v,
            "r": Web3.to_bytes(signed.r).rjust(32, b'\0'),
            "s": Web3.to_bytes(signed.s).rjust(32, b'\0'),
            "deadline": deadline
        }

    def pay_with_permit(self, router_addr, token_addr, merchant_addr, amount, order_id):
        """Combines sign_permit and on-chain submission."""
        sig = self.sign_permit(token_addr, router_addr, amount)
        router_abi = [{"inputs": [{"name": "payer", "type": "address"}, {"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}, {"name": "deadline", "type": "uint256"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "name": "payWithPermit", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=router_abi)
        order_id_bytes = self.w3.keccak(text=order_id)
        
        current_gas_price = int(self.w3.eth.gas_price * 1.2)
        with self.nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
            tx = router.functions.payWithPermit(
                self.account.address,
                Web3.to_checksum_address(token_addr),
                Web3.to_checksum_address(merchant_addr),
                amount,
                order_id_bytes,
                sig["deadline"], sig["v"], sig["r"], sig["s"]
            ).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gas': 300000,
                'gasPrice': current_gas_price
            })
            signed_tx = self.account.sign_transaction(tx)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
        return self.w3.to_hex(tx_h)

    def _execute_pay(self, router_addr, token_addr, merchant_addr, amount, order_id):
        """Standard pay method (fallback)."""
        router_abi = [{"inputs": [{"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}], "name": "pay", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=router_abi)
        order_id_bytes = self.w3.keccak(text=order_id)
        current_gas_price = int(self.w3.eth.gas_price * 1.2)
        
        with self.nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
            tx = router.functions.pay(Web3.to_checksum_address(token_addr), Web3.to_checksum_address(merchant_addr), amount, order_id_bytes).build_transaction({
                'from': self.account.address, 'nonce': nonce, 'gas': 200000, 'gasPrice': current_gas_price
            })
            signed_tx = self.account.sign_transaction(tx)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
        return self.w3.to_hex(tx_h)
