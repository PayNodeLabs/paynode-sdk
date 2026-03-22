from enum import Enum
from typing import Any, Optional

class ErrorCode(str, Enum):
    rpc_error = 'rpc_error'
    insufficient_funds = 'insufficient_funds'
    amount_too_low = 'amount_too_low'
    token_not_accepted = 'token_not_accepted'
    transaction_failed = 'transaction_failed'
    duplicate_transaction = 'duplicate_transaction'
    invalid_receipt = 'invalid_receipt'
    internal_error = 'internal_error'
    transaction_not_found = 'transaction_not_found'
    wrong_contract = 'wrong_contract'
    order_mismatch = 'order_mismatch'
    missing_receipt = 'missing_receipt'

class PayNodeException(Exception):
    def __init__(self, message: str, code: ErrorCode, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
