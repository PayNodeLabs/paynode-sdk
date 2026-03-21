import time
import logging
import threading
import requests
from web3 import Web3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .constants import PAYNODE_ROUTER_ADDRESS, BASE_USDC_ADDRESS, BASE_USDC_DECIMALS
from .errors import PayNodeException, ErrorCode

logger = logging.getLogger("paynode_sdk.client")

class PayNodeAgentClient:
    def __init__(self, rpc_urls: list, private_key: str):
        self.rpc_urls = rpc_urls
        self.w3 = self._init_w3()
        # Initialize account and discard private key string to prevent Traceback leaks
        self.account = self.w3.eth.account.from_key(private_key)
        self.nonce_lock = threading.Lock()
        
        # Setup session with standard HTTP retries for non-402 errors
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
        for rpc in self.rpc_urls:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
                if w3.is_connected():
                    return w3
            except Exception:
                continue
        raise PayNodeException("Failed to connect to any RPC URL", ErrorCode.RPC_ERROR)

    def get(self, url, **kwargs):
        return self._request_with_402_retry("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request_with_402_retry("POST", url, **kwargs)

    def _request_with_402_retry(self, method, url, max_retries=3, **kwargs):
        for attempt in range(max_retries):
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 402:
                logger.info("💡 [PayNode-PY] 402 Detected. Handling payment...")
                try:
                    kwargs = self._handle_402(response.headers, **kwargs)
                except Exception as e:
                    if isinstance(e, PayNodeException):
                        raise
                    raise PayNodeException(f"Payment execution failed: {str(e)}", ErrorCode.INTERNAL_ERROR)
                time.sleep(1) # Backoff before retry
                continue
            return response
        return response

    def _handle_402(self, headers, **kwargs):
        router_addr = headers.get('x-paynode-contract')
        merchant_addr = headers.get('x-paynode-merchant')
        amount_raw = int(headers.get('x-paynode-amount', 0))
        token_addr = headers.get('x-paynode-token-address')
        order_id = headers.get('x-paynode-order-id')

        try:
            self._ensure_allowance(token_addr, router_addr, amount_raw)
            tx_hash = self._execute_pay(router_addr, token_addr, merchant_addr, amount_raw, order_id)
            logger.info(f"✅ [PayNode-PY] Payment successful: {tx_hash}")
        except ValueError as e:
            err_msg = str(e).lower()
            if "insufficient funds" in err_msg:
                raise PayNodeException("Insufficient funds for gas or token.", ErrorCode.INSUFFICIENT_FUNDS)
            raise PayNodeException(f"Transaction failed: {str(e)}", ErrorCode.TRANSACTION_FAILED)
        except Exception as e:
            if isinstance(e, PayNodeException):
                raise
            raise PayNodeException(f"Unknown error during payment: {str(e)}", ErrorCode.INTERNAL_ERROR)

        retry_headers = kwargs.get('headers', {}).copy()
        retry_headers.update({
            'x-paynode-receipt': tx_hash,
            'x-paynode-order-id': order_id
        })
        kwargs['headers'] = retry_headers
        return kwargs

    def _ensure_allowance(self, token_addr, spender_addr, amount):
        token_abi = [
            {"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            {"constant": False, "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
        ]
        token = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=token_abi)
        allowance = token.functions.allowance(self.account.address, Web3.to_checksum_address(spender_addr)).call()
        
        if allowance < amount:
            logger.info("🔐 [PayNode-PY] Allowance too low. Granting Infinite Approval...")
            current_gas_price = int(self.w3.eth.gas_price * 1.2)
            
            with self.nonce_lock:
                nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
                tx = token.functions.approve(Web3.to_checksum_address(spender_addr), 2**256 - 1).build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': current_gas_price
                })
                signed_tx = self.account.sign_transaction(tx)
                tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(f"⏳ Waiting for approval confirmation: {self.w3.to_hex(tx_h)}...")
            self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)

    def _execute_pay(self, router_addr, token_addr, merchant_addr, amount, order_id):
        router_abi = [
            {"inputs": [{"name": "t", "type": "address"}, {"name": "m", "type": "address"}, {"name": "a", "type": "uint256"}, {"name": "o", "type": "bytes32"}], "name": "pay", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
            {"inputs": [{"name": "payer", "type": "address"}, {"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}, {"name": "deadline", "type": "uint256"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "name": "payWithPermit", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
        ]
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=router_abi)
        order_id_bytes = self.w3.keccak(text=order_id)

        current_gas_price = int(self.w3.eth.gas_price * 1.2)

        with self.nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
            tx = router.functions.pay(
                Web3.to_checksum_address(token_addr),
                Web3.to_checksum_address(merchant_addr),
                amount,
                order_id_bytes
            ).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': current_gas_price
            })
            signed_tx = self.account.sign_transaction(tx)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
        self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
        return self.w3.to_hex(tx_h)

    def pay_with_permit(
        self,
        router_addr: str,
        payer_address: str,
        token_addr: str,
        merchant_addr: str,
        amount: int,
        order_id: str,
        deadline: int,
        v: int,
        r: bytes,
        s: bytes
    ) -> str:
        """
        Execute payment using EIP-2612 Permit — single-tx approve + pay.
        The payer signs the permit offline, and this Agent relays it on-chain.

        Args:
            router_addr: PayNode Router contract address
            payer_address: The address that holds the tokens and signed the permit
            token_addr: ERC20 token address (must support EIP-2612)
            merchant_addr: Merchant receiving 99% of payment
            amount: Token amount in smallest unit (e.g. 1000000 = 1 USDC)
            order_id: Order identifier string
            deadline: Unix timestamp after which the permit is invalid
            v: ECDSA recovery id
            r: ECDSA signature r component (bytes32)
            s: ECDSA signature s component (bytes32)
        """
        router_abi = [
            {"inputs": [{"name": "payer", "type": "address"}, {"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}, {"name": "deadline", "type": "uint256"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "name": "payWithPermit", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
        ]
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=router_abi)
        order_id_bytes = self.w3.keccak(text=order_id)

        current_gas_price = int(self.w3.eth.gas_price * 1.2)

        try:
            with self.nonce_lock:
                nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
                tx = router.functions.payWithPermit(
                    Web3.to_checksum_address(payer_address),
                    Web3.to_checksum_address(token_addr),
                    Web3.to_checksum_address(merchant_addr),
                    amount,
                    order_id_bytes,
                    deadline,
                    v,
                    r,
                    s
                ).build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                    'gas': 300000,
                    'gasPrice': current_gas_price
                })
                signed_tx = self.account.sign_transaction(tx)
                tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
            logger.info(f"✅ [PayNode-PY] Permit payment confirmed: {self.w3.to_hex(tx_h)}")
            return self.w3.to_hex(tx_h)
        except ValueError as e:
            err_msg = str(e).lower()
            if "insufficient funds" in err_msg:
                raise PayNodeException("Insufficient funds for gas.", ErrorCode.INSUFFICIENT_FUNDS)
            raise PayNodeException(f"Permit transaction failed: {str(e)}", ErrorCode.PERMIT_FAILED)
        except Exception as e:
            if isinstance(e, PayNodeException):
                raise
            raise PayNodeException(f"Permit payment error: {str(e)}", ErrorCode.INTERNAL_ERROR)
