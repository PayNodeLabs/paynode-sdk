import asyncio
import time
import logging
import hmac
from concurrent.futures import ThreadPoolExecutor, as_completed
from .errors import ErrorCode, PayNodeException
from .constants import ACCEPTED_TOKENS, MIN_PAYMENT_AMOUNT, PAYNODE_ROUTER_ABI
from .idempotency import MemoryIdempotencyStore
from web3 import Web3
from eth_account import Account

logger = logging.getLogger("paynode_sdk.verifier")

class PayNodeVerifier:
    def __init__(self, rpc_urls=None, contract_address=None, chain_id=None, w3=None, store=None, accepted_tokens=None):
        self.w3 = w3
        if not self.w3 and rpc_urls:
            urls = rpc_urls if isinstance(rpc_urls, list) else [rpc_urls]
            
            def _check_rpc(url):
                try:
                    temp_w3 = Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': 3}))
                    if temp_w3.is_connected():
                        return temp_w3
                except Exception:
                    pass
                return None

            with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as executor:
                future_to_url = {executor.submit(_check_rpc, url): url for url in urls}
                for future in as_completed(future_to_url):
                    w3_instance = future.result()
                    if w3_instance:
                        self.w3 = w3_instance
                        logger.debug(f"⚡ [PayNode-PY] Verifier connected to RPC: {future_to_url[future]}")
                        break
            
            if not self.w3:
                raise PayNodeException(ErrorCode.rpc_error, message="All provided RPC nodes are unreachable.")
        self.contract_address = contract_address
        self.chain_id = int(chain_id) if chain_id else None
        self.store = store or MemoryIdempotencyStore()

        # Build accepted token set: user-provided or chain-default
        if accepted_tokens is not None:
            token_list = accepted_tokens
        elif self.chain_id:
            token_list = ACCEPTED_TOKENS.get(self.chain_id)
        else:
            token_list = None

        if not token_list:
            raise PayNodeException(
                ErrorCode.internal_error,
                message="Verifier requires either a valid chain_id or accepted_tokens to initialize its whitelist"
            )
        self.accepted_tokens = set(t.lower() for t in token_list)

    async def verify(self, unified_payload: dict, expected: dict, extra: dict = None) -> dict:
        """
        Unified verification entry point for X402 V3.1 (Hybrid V2).
        Routes to verify_onchain_payment or verify_transfer_with_authorization (eip3009).
        """
        try:
            # 1. Double-check Protocol Dust Limit (>= 1000)
            expected_amount = int(expected.get("amount", 0))
            if expected_amount < MIN_PAYMENT_AMOUNT:
                 return {"isValid": False, "error": PayNodeException(ErrorCode.amount_too_low)}

            # 2. Security: Token Whitelist Check
            if expected.get("tokenAddress", "").lower() not in self.accepted_tokens:
                return {"isValid": False, "error": PayNodeException(ErrorCode.token_not_accepted, message=f"Token {expected.get('tokenAddress')} not allowed")}

            payload_type = unified_payload.get("type")
            actual_payload = unified_payload.get("payload", {})
            order_id = unified_payload.get("orderId")
            
            if payload_type == "onchain":
                tx_hash = actual_payload.get("txHash")
                if not tx_hash:
                    return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Missing txHash in onchain payload")}
                
                onchain_expected = {
                    "merchantAddress": expected.get("merchantAddress"),
                    "tokenAddress": expected.get("tokenAddress"),
                    "amount": expected.get("amount"),
                    "orderId": order_id
                }
                return await self.verify_onchain_payment(tx_hash, onchain_expected)
            
            elif payload_type == "eip3009":
                token_addr = expected.get("tokenAddress")
                if not token_addr:
                    return {"isValid": False, "error": PayNodeException(ErrorCode.token_not_accepted, message="tokenAddress is required for eip3009 verification")}
                
                return await self.verify_transfer_with_authorization(
                    token_addr, 
                    actual_payload, 
                    {"to": expected.get("merchantAddress"), "value": expected.get("amount")},
                    extra
                )
            else:
                return {"isValid": False, "error": PayNodeException(ErrorCode.internal_error, message=f"Unsupported payload type: {payload_type}")}
        except Exception as e:
            if isinstance(e, PayNodeException):
                return {"isValid": False, "error": e}
            return {"isValid": False, "error": PayNodeException(ErrorCode.internal_error, message=str(e))}

    async def verify_onchain_payment(self, tx_hash, expected):
        if not self.w3:
            return {"isValid": False, "error": PayNodeException(ErrorCode.rpc_error)}

        try:
            receipt = await asyncio.to_thread(self.w3.eth.get_transaction_receipt, tx_hash)
        except Exception:
            return {"isValid": False, "error": PayNodeException(ErrorCode.transaction_not_found)}

        if receipt is None:
            return {"isValid": False, "error": PayNodeException(ErrorCode.transaction_not_found)}
            
        if receipt.get("status") == 0:
            return {"isValid": False, "error": PayNodeException(ErrorCode.transaction_failed)}

        contract = self.w3.eth.contract(address=Web3.to_checksum_address(self.contract_address), abi=PAYNODE_ROUTER_ABI)
        
        # 1. Check if the router was even involved (against 'WrongContract' vs 'InvalidReceipt')
        # Filter logs for current contract
        relevant_logs = [log for log in receipt.get("logs", []) if log.get("address", "").lower() == self.contract_address.lower()]
        if not relevant_logs:
             return {"isValid": False, "error": PayNodeException(ErrorCode.wrong_contract, message="Transaction did not interact with the expected PayNodeRouter contract")}

        try:
            processed_logs = await asyncio.to_thread(contract.events.PaymentReceived().process_receipt, {"logs": relevant_logs})
        except Exception:
             return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt)}

        if not processed_logs:
             return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="No PaymentReceived event found in router logs")}

        merchant = expected.get("merchantAddress", "").lower()
        token = expected.get("tokenAddress", "").lower()
        amount = int(expected.get("amount", 0))
        order_id_bytes = self.w3.keccak(text=expected.get("orderId", ""))

        valid_log_found = False
        found_payer = None
        order_id_mismatch_found = False
        for log in processed_logs:
            args = log.args
            is_merchant_match = hmac.compare_digest(args.get("merchant", "").lower(), merchant)
            is_token_match = hmac.compare_digest(args.get("token", "").lower(), token)
            is_amount_match = args.get("amount", 0) >= amount
            is_order_match = hmac.compare_digest(args.get("orderId"), order_id_bytes)

            if is_merchant_match and is_token_match and is_amount_match:
                if is_order_match:
                    valid_log_found = True
                    found_payer = args.get("payer")
                    break
                else:
                    order_id_mismatch_found = True
        
        if not valid_log_found:
             if order_id_mismatch_found:
                 return {"isValid": False, "error": PayNodeException(ErrorCode.order_mismatch, message="Payment log found but orderId does not match")}
             return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Payment event data mismatch")}

        if self.store:
            is_new = await self.store.check_and_set(tx_hash, 86400)
            if not is_new:
                return {"isValid": False, "error": PayNodeException(ErrorCode.duplicate_transaction)}

        return {"isValid": True, "payer": found_payer}

    async def verify_transfer_with_authorization(
        self,
        token_addr: str,
        payload: dict,
        expected: dict,
        extra: dict = None
    ) -> dict:
        """
        Verifies an EIP-3009 TransferWithAuthorization signature.
        Includes RPC state checks for balance and nonce status.
        """
        if not self.w3:
            return {"isValid": False, "error": PayNodeException(ErrorCode.rpc_error, message="Verifier web3 instance missing")}

        extra = extra or {}
        try:
            signature = payload["signature"]
            auth = payload["authorization"]
            
            # 1. Basic validation
            if not hmac.compare_digest(auth["to"].lower(), expected["to"].lower()):
                return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Recipient mismatch")}
            
            payload_value = int(auth["value"])
            expected_value = int(expected["value"])
            if payload_value < expected_value:
                return {"isValid": False, "error": PayNodeException(ErrorCode.amount_too_low)}

            # 2. Time window check
            now = int(time.time())
            if now < int(auth["validAfter"]):
                return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Authorization not yet valid")}
            if now > int(auth["validBefore"]):
                return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Authorization expired")}

            # 3. Signature verification
            chain_id = self.chain_id or await asyncio.to_thread(lambda: self.w3.eth.chain_id)
            domain = {
                "name": extra.get("name", "USD Coin"),
                "version": extra.get("version", "2"),
                "chainId": chain_id,
                "verifyingContract": Web3.to_checksum_address(token_addr)
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
                ]
            }

            auth_msg = {
                "from": Web3.to_checksum_address(auth["from"]),
                "to": Web3.to_checksum_address(auth["to"]),
                "value": payload_value,
                "validAfter": int(auth["validAfter"]),
                "validBefore": int(auth["validBefore"]),
                "nonce": Web3.to_bytes(hexstr=auth["nonce"])
            }

            structured_data = {
                "types": types,
                "domain": domain,
                "primaryType": "TransferWithAuthorization",
                "message": auth_msg
            }

            from eth_account.messages import encode_typed_data
            signable_msg = encode_typed_data(full_message=structured_data)
            recovered_address = Account.recover_message(signable_msg, signature=signature)

            if not hmac.compare_digest(recovered_address.lower(), auth["from"].lower()):
                return {"isValid": False, "error": PayNodeException(ErrorCode.invalid_receipt, message="Invalid signature")}

            # 4. Idempotency (Nonce local check)
            nonce = auth["nonce"]
            if self.store:
                is_new = await self.store.check_and_set(nonce, 86400)
                if not is_new:
                    return {"isValid": False, "error": PayNodeException(ErrorCode.duplicate_transaction, message="Nonce already used in local memory")}

            # 5. RPC State Checks (Balance & Nonce)
            token_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "account", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "payable": False,
                    "stateMutability": "view",
                    "type": "function",
                },
                {
                    "constant": True,
                    "inputs": [
                        {"name": "authorizer", "type": "address"},
                        {"name": "nonce", "type": "bytes32"}
                    ],
                    "name": "authorizationState",
                    "outputs": [{"name": "", "type": "bool"}],
                    "payable": False,
                    "stateMutability": "view",
                    "type": "function",
                }
            ]
            
            token_contract = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=token_abi)
            authorizer_address = Web3.to_checksum_address(auth["from"])
            nonce_bytes = Web3.to_bytes(hexstr=nonce)

            # Concurrent RPC calls
            try:
                balance, is_nonce_used_on_chain = await asyncio.gather(
                    asyncio.to_thread(token_contract.functions.balanceOf(authorizer_address).call),
                    asyncio.to_thread(token_contract.functions.authorizationState(authorizer_address, nonce_bytes).call)
                )
            except Exception as e:
                logger.warning(f"RPC state check failed for token {token_addr}: {e}")
                if self.store: await self.store.delete(nonce)
                return {
                    "isValid": False, 
                    "error": PayNodeException(ErrorCode.rpc_error, message=f"Cannot verify on-chain state: {e}")
                }

            if balance < payload_value:
                if self.store: await self.store.delete(nonce)
                return {"isValid": False, "error": PayNodeException(ErrorCode.insufficient_funds, message="Insufficient token balance")}

            if is_nonce_used_on_chain:
                if self.store: await self.store.delete(nonce)
                return {"isValid": False, "error": PayNodeException(ErrorCode.duplicate_transaction, message="Nonce already consumed on-chain")}

            return {"isValid": True, "payer": auth["from"]}
        except Exception as e:
            return {"isValid": False, "error": PayNodeException(ErrorCode.internal_error, message=str(e))}
