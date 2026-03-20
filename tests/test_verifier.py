import pytest
from unittest.mock import MagicMock, AsyncMock
from paynode_sdk.verifier import PayNodeVerifier
from paynode_sdk.errors import ErrorCode

@pytest.fixture
def verifier():
    return PayNodeVerifier(
        rpc_url="http://localhost:8545",
        contract_address="0x1234567890123456789012345678901234567890",
        chain_id=8453
    )

@pytest.mark.asyncio
async def test_verify_payment_not_found(verifier):
    # Mock w3.eth.get_transaction_receipt to return None
    verifier.w3.eth.get_transaction_receipt = MagicMock(return_value=None)
    
    expected = {"orderId": "order_1", "merchantAddress": "0xM", "tokenAddress": "0xT", "amount": 100}
    result = await verifier.verify_payment("0xHash", expected)
    
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.TRANSACTION_NOT_FOUND

@pytest.mark.asyncio
async def test_verify_payment_reverted(verifier):
    # Mock status = 0
    verifier.w3.eth.get_transaction_receipt = MagicMock(return_value={"status": 0})
    
    expected = {"orderId": "order_1", "merchantAddress": "0xM", "tokenAddress": "0xT", "amount": 100}
    result = await verifier.verify_payment("0xHash", expected)
    
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.TRANSACTION_FAILED

@pytest.mark.asyncio
async def test_verify_payment_double_spend(verifier):
    # Success first time
    verifier.w3.eth.get_transaction_receipt = MagicMock(return_value={
        "status": 1, 
        "to": verifier.contract_address,
        "logs": [] # Simplified for this test case
    })
    
    # Manually mock the process_receipt to return a matching event
    mock_event = MagicMock()
    # We must mock the event object in the verifier
    from eth_utils import keccak
    mock_log = {
        "args": {
            "order_id": keccak(text="order_1"), # This name might vary based on your ABI parsing
            "merchant": "0xMerchant",
            "token": "0xToken",
            "amount": 1000,
            "orderId": keccak(text="order_1")
        }
    }
    # For simplicity, we just inject into used_receipts for double spend test
    verifier.used_receipts.add("0xUsedHash")
    
    expected = {"orderId": "order_1", "merchantAddress": "0xMerchant", "tokenAddress": "0xToken", "amount": 1000}
    result = await verifier.verify_payment("0xUsedHash", expected)
    
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.RECEIPT_ALREADY_USED
