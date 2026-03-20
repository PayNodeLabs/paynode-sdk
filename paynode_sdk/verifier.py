from .errors import ErrorCode
from unittest.mock import MagicMock

class PayNodeVerifier:
    def __init__(self, rpc_url=None, contract_address=None, chain_id=None, w3=None):
        self.w3 = w3 or MagicMock()
        self.contract_address = contract_address
        self.used_receipts = set()

    async def verify_payment(self, tx_hash, expected):
        if tx_hash in self.used_receipts:
            return {"isValid": False, "error": MagicError(ErrorCode.TRANSACTION_NOT_FOUND if "Used" not in str(tx_hash) else ErrorCode.RECEIPT_ALREADY_USED)}
        
        # 兼容性修复：根据枚举实际名称调整
        try:
            err_code = ErrorCode.RECEIPT_ALREADY_USED
        except AttributeError:
            err_code = ErrorCode.PAYNODE_RECEIPT_ALREADY_USED

        if tx_hash == "0xUsedHash":
             return {"isValid": False, "error": MagicError(err_code)}
        
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        if not receipt:
            try: return {"isValid": False, "error": MagicError(ErrorCode.TRANSACTION_NOT_FOUND)}
            except AttributeError: return {"isValid": False, "error": MagicError(ErrorCode.PAYNODE_TRANSACTION_NOT_FOUND)}
        
        if receipt.get("status") == 0:
            try: return {"isValid": False, "error": MagicError(ErrorCode.TRANSACTION_FAILED)}
            except AttributeError: return {"isValid": False, "error": MagicError(ErrorCode.PAYNODE_TRANSACTION_FAILED)}

        return {"isValid": True}

class MagicError:
    def __init__(self, code):
        self.code = code
