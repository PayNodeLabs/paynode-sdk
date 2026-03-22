from enum import Enum
from typing import Any, Optional

class ErrorCode(str, Enum):
    # Authentication & Receipts
    MISSING_RECEIPT = 'PAYNODE_MISSING_RECEIPT'
    INVALID_RECEIPT = 'PAYNODE_INVALID_RECEIPT'
    RECEIPT_ALREADY_USED = 'PAYNODE_RECEIPT_ALREADY_USED'
    TRANSACTION_NOT_FOUND = 'PAYNODE_TRANSACTION_NOT_FOUND'
    TRANSACTION_FAILED = 'PAYNODE_TRANSACTION_FAILED'

    # Validation
    WRONG_CONTRACT = 'PAYNODE_WRONG_CONTRACT'
    WRONG_MERCHANT = 'PAYNODE_WRONG_MERCHANT'
    WRONG_TOKEN = 'PAYNODE_WRONG_TOKEN'
    TOKEN_NOT_ACCEPTED = 'PAYNODE_TOKEN_NOT_ACCEPTED'
    AMOUNT_TOO_LOW = 'PAYNODE_AMOUNT_TOO_LOW'
    INSUFFICIENT_FUNDS = 'PAYNODE_INSUFFICIENT_FUNDS'
    ORDER_MISMATCH = 'PAYNODE_ORDER_MISMATCH'
    PERMIT_FAILED = 'PAYNODE_PERMIT_FAILED'
    
    # System
    RPC_ERROR = 'PAYNODE_RPC_ERROR'
    INTERNAL_ERROR = 'PAYNODE_INTERNAL_ERROR'

class PayNodeException(Exception):
    def __init__(self, message: str, code: ErrorCode, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
