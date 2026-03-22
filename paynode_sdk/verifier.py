from .errors import ErrorCode, PayNodeException
from .constants import PAYNODE_ROUTER_ABI, ACCEPTED_TOKENS, MIN_PAYMENT_AMOUNT
from .idempotency import MemoryIdempotencyStore
from web3 import Web3

class PayNodeVerifier:
    def __init__(self, rpc_url=None, contract_address=None, chain_id=None, w3=None, store=None, accepted_tokens=None):
        self.w3 = w3
        if not self.w3 and rpc_url:
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
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
            return {"isValid": False, "error": PayNodeException("Verifier Provider Missing", ErrorCode.RPC_ERROR)}

        # 0. Dust Exploit Check (Minimum Payment)
        amount = int(expected.get("amount", 0))
        if amount < MIN_PAYMENT_AMOUNT:
             return {"isValid": False, "error": PayNodeException(
                f"Payment amount {amount} is below the minimum threshold of {MIN_PAYMENT_AMOUNT}.",
                ErrorCode.AMOUNT_TOO_LOW
            )}

        # 1. Token Whitelist Check (Anti-FakeToken)
        expected_token = expected.get("tokenAddress", "").lower()
        if self.accepted_tokens and expected_token not in self.accepted_tokens:
            return {"isValid": False, "error": PayNodeException(
                f"Token {expected.get('tokenAddress')} is not in the accepted whitelist.",
                ErrorCode.TOKEN_NOT_ACCEPTED
            )}

        try:
            is_new = await self.store.check_and_set(tx_hash, 86400) # 24 hour TTL
            if not is_new:
                return {"isValid": False, "error": PayNodeException("Receipt already used", ErrorCode.RECEIPT_ALREADY_USED)}
        except Exception as e:
            return {"isValid": False, "error": PayNodeException("Store Error", ErrorCode.INTERNAL_ERROR, details=str(e))}

        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return {"isValid": False, "error": PayNodeException("Transaction not found", ErrorCode.TRANSACTION_NOT_FOUND)}

        if not receipt:
            return {"isValid": False, "error": PayNodeException("Transaction not found", ErrorCode.TRANSACTION_NOT_FOUND)}
        
        if receipt.get("status") == 0:
            return {"isValid": False, "error": PayNodeException("Transaction failed", ErrorCode.TRANSACTION_FAILED)}

        if not receipt.get("to") or receipt.get("to", "").lower() != self.contract_address.lower():
            return {"isValid": False, "error": PayNodeException("Wrong contract", ErrorCode.WRONG_CONTRACT)}

        contract = self.w3.eth.contract(address=Web3.to_checksum_address(self.contract_address), abi=PAYNODE_ROUTER_ABI)
        
        try:
            logs = contract.events.PaymentReceived().process_receipt(receipt)
        except Exception:
            return {"isValid": False, "error": PayNodeException("Invalid receipt format", ErrorCode.INVALID_RECEIPT)}

        if not logs:
            return {"isValid": False, "error": PayNodeException("No valid PaymentReceived event found", ErrorCode.INVALID_RECEIPT)}

        # Find the valid log
        merchant = expected.get("merchantAddress", "").lower()
        token = expected.get("tokenAddress", "").lower()
        amount = int(expected.get("amount", 0))
        
        order_id_bytes = self.w3.keccak(text=expected.get("orderId", ""))

        valid = False
        for log in logs:
            args = log.args
            
            if args.get("orderId") != order_id_bytes:
                continue
                
            if args.get("merchant", "").lower() != merchant:
                continue
                
            if args.get("token", "").lower() != token:
                continue
                
            if args.get("amount", 0) < amount:
                continue

            if self.chain_id and args.get("chainId") != self.chain_id:
                continue

            valid = True
            break

        if not valid:
            return {"isValid": False, "error": PayNodeException("Payment criteria mismatch", ErrorCode.INVALID_RECEIPT)}

        return {"isValid": True}
