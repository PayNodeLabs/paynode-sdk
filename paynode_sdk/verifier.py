from .errors import ErrorCode, PayNodeException
from .constants import PAYNODE_ROUTER_ABI, ACCEPTED_TOKENS, MIN_PAYMENT_AMOUNT
from .idempotency import MemoryIdempotencyStore
from web3 import Web3

class PayNodeVerifier:
    def __init__(self, rpc_urls=None, contract_address=None, chain_id=None, w3=None, store=None, accepted_tokens=None):
        self.w3 = w3
        if not self.w3 and rpc_urls:
            urls = rpc_urls if isinstance(rpc_urls, list) else [rpc_urls]
            for rpc in urls:
                try:
                    temp_w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 5}))
                    if temp_w3.is_connected():
                        self.w3 = temp_w3
                        break
                except Exception:
                    continue
            if not self.w3:
                raise PayNodeException("Failed to connect to any provided RPC nodes.", ErrorCode.rpc_error)
        self.contract_address = contract_address
        self.chain_id = int(chain_id) if chain_id else None
        self.store = store or MemoryIdempotencyStore()

        # Build accepted token set: user-provided or chain-default
        # accepted_tokens=None → use chain default; accepted_tokens=[] → explicitly disable whitelist
        if accepted_tokens is not None:
            token_list = accepted_tokens
        elif self.chain_id:
            token_list = ACCEPTED_TOKENS.get(self.chain_id)
        else:
            token_list = None
        self.accepted_tokens = set(t.lower() for t in token_list) if token_list else None

    async def verify_payment(self, tx_hash, expected):
        if not self.w3:
            return {"isValid": False, "error": PayNodeException("Verifier Provider Missing", ErrorCode.rpc_error)}

        # 0. Dust Exploit Check (Minimum Payment)
        amount = int(expected.get("amount", 0))
        if amount < MIN_PAYMENT_AMOUNT:
             return {"isValid": False, "error": PayNodeException(
                f"Payment amount {amount} is below the minimum threshold of {MIN_PAYMENT_AMOUNT}.",
                ErrorCode.amount_too_low
            )}

        # 1. Token Whitelist Check (Anti-FakeToken)
        expected_token = expected.get("tokenAddress", "").lower()
        if self.accepted_tokens and expected_token not in self.accepted_tokens:
            return {"isValid": False, "error": PayNodeException(
                f"Token {expected.get('tokenAddress')} is not in the accepted whitelist.",
                ErrorCode.token_not_accepted
            )}

        try:
            is_new = await self.store.check_and_set(tx_hash, 86400) # 24 hour TTL
            if not is_new:
                return {"isValid": False, "error": PayNodeException("This transaction hash has already been consumed.", ErrorCode.duplicate_transaction)}
        except Exception as e:
            return {"isValid": False, "error": PayNodeException("Store Error", ErrorCode.internal_error, details=str(e))}

        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return {"isValid": False, "error": PayNodeException("Transaction not found", ErrorCode.transaction_not_found)}

        if not receipt:
            return {"isValid": False, "error": PayNodeException("Transaction not found", ErrorCode.transaction_not_found)}
        
        if receipt.get("status") == 0:
            return {"isValid": False, "error": PayNodeException("Transaction failed", ErrorCode.transaction_failed)}

        contract = self.w3.eth.contract(address=Web3.to_checksum_address(self.contract_address), abi=PAYNODE_ROUTER_ABI)
        
        try:
            logs = contract.events.PaymentReceived().process_receipt(receipt)
        except Exception:
            return {"isValid": False, "error": PayNodeException("Invalid receipt format", ErrorCode.invalid_receipt)}

        if not logs:
            return {"isValid": False, "error": PayNodeException("No valid PaymentReceived event found", ErrorCode.invalid_receipt)}

        # Find and validate the specific log
        merchant = expected.get("merchantAddress", "").lower()
        token = expected.get("tokenAddress", "").lower()
        amount = int(expected.get("amount", 0))
        order_id_bytes = self.w3.keccak(text=expected.get("orderId", ""))

        last_error = None
        valid_log_found = False

        for log in logs:
            if log.address.lower() != self.contract_address.lower():
                continue
                
            args = log.args
            
            # 4. Verify OrderId
            if args.get("orderId") != order_id_bytes:
                last_error = PayNodeException("OrderId in receipt does not match requested ID.", ErrorCode.order_mismatch)
                continue
                
            # 5. Verify Merchant
            if args.get("merchant", "").lower() != merchant:
                last_error = PayNodeException("Payment went to a different merchant.", ErrorCode.invalid_receipt)
                continue
                
            # 6. Verify Token
            if args.get("token", "").lower() != token:
                last_error = PayNodeException("Payment used unexpected token.", ErrorCode.invalid_receipt)
                continue
                
            # 7. Verify Amount
            if args.get("amount", 0) < amount:
                last_error = PayNodeException("Payment amount is below required price.", ErrorCode.invalid_receipt)
                continue

            # 8. Verify ChainId
            if self.chain_id and args.get("chainId") != self.chain_id:
                last_error = PayNodeException("ChainId mismatch. Invalid network.", ErrorCode.invalid_receipt)
                continue

            valid_log_found = True
            break

        if not valid_log_found:
            return {"isValid": False, "error": last_error or PayNodeException("No matching payment event found.", ErrorCode.invalid_receipt)}

        return {"isValid": True}
