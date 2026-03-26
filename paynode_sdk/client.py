import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from urllib.parse import urlparse
from eth_account.messages import encode_typed_data
from web3 import Web3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .constants import PAYNODE_ROUTER_ADDRESS, BASE_USDC_ADDRESS, BASE_USDC_DECIMALS, BASE_RPC_URLS, ACCEPTED_TOKENS, MIN_PAYMENT_AMOUNT, PAYNODE_ROUTER_ABI
from .errors import PayNodeException, ErrorCode

logger = logging.getLogger("paynode_sdk.client")

class PayNodeAgentClient:
    """
    The main PayNode Client for AI Agents (v3.1).
    Automatically handles the x402 'Payment Required' handshake.
    Supports RPC redundancy, EIP-2612 Permit, and EIP-3009 Authorization.
    """
    def __init__(self, private_key: str, rpc_urls: list | str = BASE_RPC_URLS):
        self.rpc_urls = rpc_urls if isinstance(rpc_urls, list) else [rpc_urls]
        self.w3 = self._init_w3()
        self.current_rpc_index = 0
        
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
        """Finds a working RPC from the list concurrently (Faster initialization)."""
        
        def _check_rpc(rpc_url):
            try:
                temp_w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 3}))
                if temp_w3.is_connected():
                    return temp_w3
                return None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(len(self.rpc_urls), 5)) as executor:
            future_to_url = {executor.submit(_check_rpc, url): url for url in self.rpc_urls}
            # Return the first one that succeeds
            for future in as_completed(future_to_url):
                w3_instance = future.result()
                if w3_instance:
                    logger.debug(f"⚡ [PayNode-PY] Connected to RPC: {future_to_url[future]}")
                    return w3_instance
                    
        raise PayNodeException(ErrorCode.rpc_error, message="All provided RPC nodes are unreachable.")

    def _rotate_rpc(self):
        """Switches to the next available RPC node in the list."""
        self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_urls)
        new_url = self.rpc_urls[self.current_rpc_index]
        logger.warning(f"⚠️ [PayNode-PY] RPC failure detected. Rotating to: {new_url}")
        self.w3 = Web3(Web3.HTTPProvider(new_url, request_kwargs={'timeout': 10}))

    def _call_with_failover(self, func, *args, **kwargs):
        """Wrapper to retry a web3 call with RPC failover."""
        for attempt in range(len(self.rpc_urls)):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < len(self.rpc_urls) - 1:
                    self._rotate_rpc()
                else:
                    raise e

    def request_gate(self, url: str, method: str = "GET", **kwargs):
        """The high-level autonomous method handling 402 loop."""
        return self._request_with_402_retry(method.upper(), url, **kwargs)

    def get(self, url, **kwargs):
        return self.request_gate(url, "GET", **kwargs)

    def post(self, url, **kwargs):
        return self.request_gate(url, "POST", **kwargs)

    def _request_with_402_retry(self, method: str, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
        response = None
        for attempt in range(max_retries):
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 402:
                logger.info(f"💡 [PayNode-PY] 402 Detected (Attempt {attempt+1}/{max_retries}). Analyzing protocol version...")
                
                # Check for x402 v2 (JSON body or X-402-Required header)
                content_type = response.headers.get('Content-Type', '')
                b64_required = response.headers.get('X-402-Required')
                order_id = response.headers.get('X-402-Order-Id')
                
                body = None
                if 'application/json' in content_type:
                    try:
                        body = response.json()
                    except Exception as e:
                        logger.debug(f"⚠️ [PayNode-PY] Failed to parse 402 JSON body: {e}")
                
                if not body and b64_required:
                    try:
                        import base64
                        import json
                        body = json.loads(base64.b64decode(b64_required).decode())
                    except Exception as e:
                        logger.warning(f"❌ [PayNode-PY] Failed to decode X-402-Required header: {e}")

                if body and body.get('x402Version') == 2:
                    logger.info("🚀 [PayNode-PY] x402 v2 detected. Handling autonomous payment...")
                    if order_id: body['orderId'] = order_id
                    kwargs = self._handle_x402_v2(url, body, **kwargs)
                    continue

                raise PayNodeException(ErrorCode.internal_error, message="Unsupported or malformed 402 response")
            
            return response

        if response and response.status_code == 402:
            raise PayNodeException(ErrorCode.internal_error, message="Still 402 after all payment attempts. The server may have rejected the payment or authorization.")
        return response

    def _handle_x402_v2(self, url: str, requirements: dict, **kwargs) -> dict:
        """
        Internal handler for X402 V2/V3.1 protocol.
        Analyzes requirements, executes payment, and returns updated kwargs for retrying the request.
        """
        chain_id = self.w3.eth.chain_id
        caip2_chain_id = f"eip155:{chain_id}"

        # Select suitable requirement
        requirement = next((req for req in requirements.get('accepts', []) 
                         if req.get('network') == caip2_chain_id), None)

        if not requirement:
            raise PayNodeException(ErrorCode.internal_error, message=f"No compatible payment requirement found for network {caip2_chain_id}")

        # 🛡️ Token Whitelist Check
        chain_tokens = ACCEPTED_TOKENS.get(chain_id, [])
        if chain_tokens and requirement.get('asset').lower() not in [t.lower() for t in chain_tokens]:
            raise PayNodeException(ErrorCode.token_not_accepted, message=f"Token {requirement['asset']} is not in the whitelist for chain {chain_id}")

        logger.info(f"💡 [PayNode-PY] Payment request (v2): {requirement['amount']} atomic units of {requirement['asset']} to {requirement['payTo']}")
        
        # Dust limit check
        if int(requirement['amount']) < MIN_PAYMENT_AMOUNT:
            raise PayNodeException(ErrorCode.amount_too_low, message=f"Payment amount {requirement['amount']} is below the minimum dust limit of {MIN_PAYMENT_AMOUNT}")

        order_id = requirement.get('orderId') or requirements.get('orderId') or urlparse(url).path
        
        payload_data = {}
        ptype = requirement.get('type', 'onchain')

        if ptype == 'eip3009':
            valid_after = int(time.time()) - 60
            valid_before = int(time.time()) + requirement.get('maxTimeoutSeconds', 3600)
            import os
            nonce = "0x" + os.urandom(32).hex()

            try:
                payload_data = self.sign_transfer_with_authorization(
                    requirement['asset'],
                    requirement['payTo'],
                    int(requirement['amount']),
                    valid_after,
                    valid_before,
                    nonce,
                    requirement.get('extra', {})
                )
            except Exception as e:
                raise PayNodeException(ErrorCode.transaction_failed, message="Failed to sign payment authorization", details=e)
        else:
            # type: 'onchain'
            router_addr = requirement.get('router')
            if not router_addr:
                raise PayNodeException(ErrorCode.internal_error, message="On-chain payment required but no router address provided.")

            logger.info(f"⚡ [PayNode-PY] Executing on-chain payment to {requirement['payTo']}...")
            amount = int(requirement['amount'])
            asset = requirement['asset']
            allowance = self._get_allowance(asset, router_addr)

            if allowance >= amount:
                try:
                    tx_hash = self.pay(router_addr, asset, requirement['payTo'], amount, order_id)
                except Exception as e:
                    logger.warning(f"⚠️ [PayNode-PY] Direct pay failed (possibly allowance race), falling back to permit: {e}")
                    tx_hash = self.pay_with_permit(router_addr, asset, requirement['payTo'], amount, order_id, version=requirement.get('extra', {}).get('version', '2'))
            else:
                tx_hash = self.pay_with_permit(router_addr, asset, requirement['payTo'], amount, order_id, version=requirement.get('extra', {}).get('version', '2'))
            
            payload_data = {"txHash": tx_hash}

        # Unified Payload for v3.1
        payment_payload = {
            "version": "3.1",
            "type": ptype,
            "orderId": order_id,
            "payload": payload_data
        }

        logger.info(f"✅ [PayNode-PY] {ptype} payment prepared. Retrying request...")
        
        import json
        import base64
        b64_payload = base64.b64encode(json.dumps(payment_payload).encode()).decode()

        retry_headers = kwargs.get('headers', {}).copy()
        retry_headers.update({
            'Content-Type': 'application/json',
            'X-402-Payload': b64_payload,
            'X-402-Order-Id': order_id
        })
        kwargs['headers'] = retry_headers
        return kwargs

    def sign_transfer_with_authorization(self, token_addr, to, amount, valid_after, valid_before, nonce, extra=None):
        extra = extra or {}
        token_addr = Web3.to_checksum_address(token_addr)
        to = Web3.to_checksum_address(to)
        
        domain = {
            "name": extra.get("name", "USD Coin"),
            "version": extra.get("version", "2"),
            "chainId": self.w3.eth.chain_id,
            "verifyingContract": token_addr,
        }
        
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        }
        
        message = {
            "from": self.account.address,
            "to": to,
            "value": int(amount),
            "validAfter": int(valid_after),
            "validBefore": int(valid_before),
            "nonce": Web3.to_bytes(hexstr=nonce),
        }
        
        structured_data = {
            "types": types,
            "domain": domain,
            "primaryType": "TransferWithAuthorization",
            "message": message,
        }
        
        signed = self.account.sign_typed_data(full_message=structured_data)
        
        return {
            "signature": signed.signature.hex(),
            "authorization": {
                "from": self.account.address,
                "to": to,
                "value": str(amount),
                "validAfter": str(valid_after),
                "validBefore": str(valid_before),
                "nonce": nonce
            }
        }

    def _get_allowance(self, token_addr, spender_addr):
        return self._call_with_failover(self.__get_allowance_raw, token_addr, spender_addr)

    def __get_allowance_raw(self, token_addr, spender_addr):
        abi = [{"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]
        token = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=abi)
        return token.functions.allowance(self.account.address, Web3.to_checksum_address(spender_addr)).call()

    def sign_permit(self, token_addr: str, spender_addr: str, amount: int, deadline: int = None, version: str = "2"):
        if deadline is None:
            deadline = int(time.time()) + 3600
        
        token_addr = Web3.to_checksum_address(token_addr)
        spender_addr = Web3.to_checksum_address(spender_addr)
        
        abi = [
            {"inputs": [{"name": "o", "type": "address"}], "name": "nonces", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
            {"inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"}
        ]
        token = self.w3.eth.contract(address=token_addr, abi=abi)
        nonce = token.functions.nonces(self.account.address).call()
        name = token.functions.name().call()
        chain_id = self.w3.eth.chain_id

        domain = {"name": name, "version": version, "chainId": chain_id, "verifyingContract": token_addr}
        message = {"owner": self.account.address, "spender": spender_addr, "value": amount, "nonce": nonce, "deadline": deadline}
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
            ],
            "Permit": [
                {"name": "owner", "type": "address"}, {"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"}, {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        }
        structured_data = {"types": types, "domain": domain, "primaryType": "Permit", "message": message}
        signed = self.account.sign_typed_data(full_message=structured_data)
        
        # NOTE: r/s padding to 32 bytes ensures bytes32 compatibility
        r_bytes = Web3.to_bytes(signed.r).rjust(32, b'\0')
        s_bytes = Web3.to_bytes(signed.s).rjust(32, b'\0')
        
        return {"v": signed.v, "r": r_bytes, "s": s_bytes, "deadline": deadline}

    def pay_with_permit(self, router_addr, token_addr, merchant_addr, amount, order_id, version="2"):
        return self._call_with_failover(self.__pay_with_permit_raw, router_addr, token_addr, merchant_addr, amount, order_id, version)

    def __pay_with_permit_raw(self, router_addr, token_addr, merchant_addr, amount, order_id, version="2"):
        sig = self.sign_permit(token_addr, router_addr, amount, version=version)
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=PAYNODE_ROUTER_ABI)
        order_id_bytes = self.w3.keccak(text=order_id)
        current_gas_price = int(self.w3.eth.gas_price * 1.2)
        with self.nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
            tx = router.functions.payWithPermit(self.account.address, Web3.to_checksum_address(token_addr), Web3.to_checksum_address(merchant_addr), amount, order_id_bytes, sig["deadline"], sig["v"], sig["r"], sig["s"]).build_transaction({'from': self.account.address, 'nonce': nonce, 'gas': 300000, 'gasPrice': current_gas_price})
            signed_tx = self.account.sign_transaction(tx)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
        return self.w3.to_hex(tx_h)

    def pay(self, router_addr, token_addr, merchant_addr, amount, order_id):
        return self._call_with_failover(self.__pay_raw, router_addr, token_addr, merchant_addr, amount, order_id)

    def __pay_raw(self, router_addr, token_addr, merchant_addr, amount, order_id):
        router = self.w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=PAYNODE_ROUTER_ABI)
        order_id_bytes = self.w3.keccak(text=order_id)
        current_gas_price = int(self.w3.eth.gas_price * 1.2)
        with self.nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address, 'pending')
            tx = router.functions.pay(Web3.to_checksum_address(token_addr), Web3.to_checksum_address(merchant_addr), amount, order_id_bytes).build_transaction({'from': self.account.address, 'nonce': nonce, 'gas': 200000, 'gasPrice': current_gas_price})
            signed_tx = self.account.sign_transaction(tx)
            tx_h = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)
        return self.w3.to_hex(tx_h)
