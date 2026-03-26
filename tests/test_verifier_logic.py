import pytest
from unittest.mock import MagicMock, patch
from web3 import Web3
from paynode_sdk import PayNodeVerifier, ErrorCode, PayNodeException

@pytest.fixture
def verifier():
    with patch('paynode_sdk.verifier.Web3') as mock_w3:
        mock_instance = mock_w3.return_value
        mock_instance.is_connected.return_value = True
        # Mock eth provider structure
        mock_instance.eth = MagicMock()
        mock_instance.keccak.side_effect = Web3.keccak
        return PayNodeVerifier(
            rpc_urls="http://localhost",
            contract_address="0x" + "a" * 40,
            chain_id=84532
        )

@pytest.mark.asyncio
async def test_verify_payment_invalid_receipt(verifier):
    """Checks handling of missing transaction receipt."""
    verifier.w3.eth.get_transaction_receipt.return_value = None
    result = await verifier.verify_onchain_payment("0xHash", {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000
    })
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.transaction_not_found

@pytest.mark.asyncio
async def test_verify_payment_wrong_contract(verifier):
    """Checks rejection of logs from unauthorized contract addresses or no logs."""
    mock_receipt = {"id": "0x123", "status": 1, "logs": []}
    
    # Mock behavior of process_receipt when no logs are provided
    mock_contract = MagicMock()
    mock_contract.events.PaymentReceived().process_receipt.return_value = [] # No valid logs
    verifier.w3.eth.contract.return_value = mock_contract
    verifier.w3.eth.get_transaction_receipt.return_value = mock_receipt
    
    payload = {"type": "onchain", "payload": {"txHash": "0xHash"}}
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000
    })
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.wrong_contract

@pytest.mark.asyncio
async def test_dust_limit_rejection(verifier):
    """Checks rejection of dust payments (<1000 atomic units)."""
    # Test through unify verify() endpoint
    payload = {
        "type": "onchain",
        "orderId": "test-dust",
        "payload": {"txHash": "0xHash"}
    }
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 500  # Below 1000
    })
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.amount_too_low

@pytest.mark.asyncio
async def test_verify_payment_non_whitelisted_token(verifier):
    """Checks rejection of non-whitelisted tokens."""
    # verifier.accepted_tokens is initialized based on chain_id 84532 or default
    payload = {"type": "onchain", "payload": {"txHash": "0xHash"}}
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x" + "f" * 40, # Random non-whitelisted token
        "amount": 2000
    })
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.token_not_accepted
@pytest.mark.asyncio
async def test_verify_payment_order_mismatch(verifier):
    """Checks ErrorCode.order_mismatch when PaymentReceived log found but orderId doesn't match."""
    # 🧪 Prepare logs that match merchant/token/amount but have WRONG orderId
    mock_log = MagicMock()
    mock_log.args = {
        "merchant": "0xMerchant",
        "token": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000,
        "orderId": b"wrong_order_id_bytes_32" # Does not match expected (which will be keccak('test-order'))
    }
    
    mock_contract = MagicMock()
    mock_contract.events.PaymentReceived().process_receipt.return_value = [mock_log]
    
    # Setup w3 mocks
    verifier.w3.eth.contract.return_value = mock_contract
    verifier.w3.eth.get_transaction_receipt.return_value = {
        "status": 1, 
        "logs": [{"address": verifier.contract_address.lower()}] # At least one log to trigger WrongContract check passing
    }
    
    payload = {
        "type": "onchain", 
        "orderId": "test-order",
        "payload": {"txHash": "0xHash"}
    }
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000
    })
    
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.order_mismatch

@pytest.mark.asyncio
async def test_verify_valid_payment(verifier):
    """Checks success path for on-chain payment."""
    mock_log = MagicMock()
    mock_log.args = {
        "merchant": "0xMerchant",
        "token": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000,
        "orderId": Web3.keccak(text="test-order")
    }
    
    mock_contract = MagicMock()
    mock_contract.events.PaymentReceived().process_receipt.return_value = [mock_log]
    verifier.w3.eth.contract.return_value = mock_contract
    verifier.w3.eth.get_transaction_receipt.return_value = {
        "status": 1,
        "logs": [{"address": verifier.contract_address.lower()}]
    }
    
    payload = {
        "type": "onchain",
        "orderId": "test-order",
        "payload": {"txHash": "0xValidHash"}
    }
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000
    })
    assert result["isValid"] is True

@pytest.mark.asyncio
async def test_duplicate_transaction(verifier):
    """Checks idempotency by ensuring the same hash cannot be verified twice."""
    mock_log = MagicMock()
    mock_log.args = {
        "merchant": "0xMerchant",
        "token": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000,
        "orderId": Web3.keccak(text="test-order")
    }
    mock_contract = MagicMock()
    mock_contract.events.PaymentReceived().process_receipt.return_value = [mock_log]
    verifier.w3.eth.contract.return_value = mock_contract
    verifier.w3.eth.get_transaction_receipt.return_value = {
        "status": 1,
        "logs": [{"address": verifier.contract_address.lower()}]
    }

    payload = {"type": "onchain", "orderId": "test-order", "payload": {"txHash": "0xDup"}}
    # Manual set to simulate previous success
    await verifier.store.check_and_set("0xDup", 86400)
    
    result = await verifier.verify(payload, {
        "merchantAddress": "0xMerchant",
        "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
        "amount": 2000
    })
    assert result["isValid"] is False
    assert result["error"].code == ErrorCode.duplicate_transaction

@pytest.mark.asyncio
async def test_verify_eip3009_valid(verifier):
    """Checks success path for EIP-3009 (Transfer with Authorization)."""
    from eth_account import Account
    
    # Setup test account
    priv_key = "0x" + "1" * 64
    account = Account.from_key(priv_key)
    from_addr = account.address
    to_addr = "0x" + "3" * 40
    token_addr = "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0"
    nonce = "0x" + "2" * 64
    
    auth = {
        "from": from_addr,
        "to": to_addr,
        "value": 2000,
        "validAfter": 0,
        "validBefore": 2000000000,
        "nonce": nonce
    }
    
    # Mock chain_id
    verifier.chain_id = 84532
    
    # Mock RPC state calls
    mock_token = MagicMock()
    mock_token.functions.balanceOf().call.return_value = 5000
    mock_token.functions.authorizationState().call.return_value = False
    verifier.w3.eth.contract.return_value = mock_token
    
    # Sign payload
    domain = {
        "name": "USD Coin",
        "version": "2",
        "chainId": 84532,
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
    structured_data = {
        "types": types,
        "domain": domain,
        "primaryType": "TransferWithAuthorization",
        "message": auth
    }
    # Fix: Use full_message to match the SDK expectation
    from eth_account.messages import encode_typed_data
    signable_msg = encode_typed_data(full_message=structured_data)
    signature = account.sign_message(signable_msg).signature.hex()
    
    payload = {
        "type": "eip3009",
        "payload": {
            "signature": signature,
            "authorization": auth
        }
    }
    
    result = await verifier.verify(payload, {
        "merchantAddress": to_addr,
        "tokenAddress": token_addr,
        "amount": 2000
    })
    
    assert result["isValid"] is True

@pytest.mark.asyncio
async def test_verify_eip3009_insufficient_balance(verifier):
    """Checks EIP-3009 failure due to low authorizer balance."""
    # Use valid hex for nonce
    nonce = "0x" + "f" * 64
    from_addr = "0x" + "d" * 40
    to_addr = "0x" + "e" * 40
    auth = {
        "from": from_addr, "to": to_addr, "value": 2000, "validAfter": 0, "validBefore": 2000000000, "nonce": nonce
    }
    # Mock low balance
    mock_token = MagicMock()
    mock_token.functions.balanceOf().call.return_value = 500 # Less than 2000
    mock_token.functions.authorizationState().call.return_value = False
    verifier.w3.eth.contract.return_value = mock_token
    
    # Skip signature check by wrapping the inner logic or mocking recover
    with patch('eth_account.Account.recover_message', return_value=from_addr):
        payload = {"type": "eip3009", "payload": {"signature": "0x" + "s" * 130, "authorization": auth}}
        result = await verifier.verify(payload, {
            "merchantAddress": to_addr, "tokenAddress": "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0", "amount": 2000
        })
        assert result["isValid"] is False
        assert result["error"].code == ErrorCode.insufficient_funds
