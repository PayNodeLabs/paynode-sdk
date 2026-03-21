import pytest
from unittest.mock import MagicMock, AsyncMock
from paynode_sdk.verifier import PayNodeVerifier
from paynode_sdk.errors import ErrorCode

@pytest.fixture
def verifier():
    """Verifier with whitelist DISABLED (accepted_tokens=[]) for unit tests using mock addresses."""
    return PayNodeVerifier(
        rpc_url="http://localhost:8545",
        contract_address="0x1234567890123456789012345678901234567890",
        chain_id=8453,
        accepted_tokens=[]  # Empty list = whitelist disabled
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
    
    # Simulate first usage directly into the new IdempotencyStore
    await verifier.store.check_and_set("0xUsedHash", 86400)
    
    expected = {"orderId": "order_1", "merchantAddress": "0xMerchant", "tokenAddress": "0xToken", "amount": 1000}
    result = await verifier.verify_payment("0xUsedHash", expected)
    
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.RECEIPT_ALREADY_USED


@pytest.mark.asyncio
async def test_token_whitelist_rejects_fake_token():
    """Token whitelist should reject tokens not in the accepted list."""
    verifier = PayNodeVerifier(
        rpc_url="http://localhost:8545",
        contract_address="0x1234567890123456789012345678901234567890",
        chain_id=8453,
        accepted_tokens=["0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
    )

    expected = {
        "orderId": "order_1",
        "merchantAddress": "0xM",
        "tokenAddress": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",  # Not in whitelist
        "amount": 100
    }
    result = await verifier.verify_payment("0xHash", expected)

    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.TOKEN_NOT_ACCEPTED


@pytest.mark.asyncio
async def test_token_whitelist_allows_valid_token():
    """Token whitelist should allow tokens in the accepted list (proceeds to next check)."""
    verifier = PayNodeVerifier(
        rpc_url="http://localhost:8545",
        contract_address="0x1234567890123456789012345678901234567890",
        chain_id=8453,
        accepted_tokens=["0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
    )
    # Mock RPC to return None (tx not found) — the token check should pass, then fail at next step
    verifier.w3.eth.get_transaction_receipt = MagicMock(return_value=None)

    expected = {
        "orderId": "order_1",
        "merchantAddress": "0xM",
        "tokenAddress": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # IS in whitelist
        "amount": 100
    }
    result = await verifier.verify_payment("0xHash", expected)

    assert result["isValid"] is False
    # Should pass whitelist check but fail on tx not found
    assert result["error"].code == ErrorCode.TRANSACTION_NOT_FOUND

