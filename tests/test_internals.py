import pytest
import time
from unittest.mock import MagicMock, patch
from web3 import Web3
from paynode_sdk import PayNodeAgentClient

MOCK_PK = "0x" + "1" * 64
MOCK_RPC = "https://sepolia.base.org"

@pytest.fixture
def client():
    with patch('paynode_sdk.client.Web3') as mock_w3:
        mock_instance = mock_w3.return_value
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 84532
        mock_instance.eth.account.from_key.return_value.address = "0xAgent"
        # Mock functions that might be called during init or usage
        mock_instance.keccak.side_effect = Web3.keccak
        return PayNodeAgentClient(MOCK_PK, MOCK_RPC)

def test_sign_transfer_with_authorization_structure(client):
    """Verifies that EIP-3009 signature structure is correct."""
    token = Web3.to_checksum_address("0x" + "2" * 40)
    to = Web3.to_checksum_address("0x" + "3" * 40)
    amount = 1000
    valid_after = 0
    valid_before = 9999999999
    nonce = "0x" + "a" * 64
    
    # Mock account.sign_typed_data
    mock_signed = MagicMock()
    mock_signed.signature.hex.return_value = "0xsig"
    client.account.sign_typed_data = MagicMock(return_value=mock_signed)
    
    result = client.sign_transfer_with_authorization(token, to, amount, valid_after, valid_before, nonce)
    
    assert "signature" in result
    assert result["authorization"]["value"] == "1000"
    
    # Check that structured data primaryType is correct
    structured_data = client.account.sign_typed_data.call_args[1]["full_message"]
    assert structured_data["primaryType"] == "TransferWithAuthorization"
    assert structured_data["domain"]["verifyingContract"] == token

def test_sign_permit_structure(client):
    """Verifies that EIP-2612 Permit structure is correct."""
    token = Web3.to_checksum_address("0x" + "2" * 40)
    spender = Web3.to_checksum_address("0x" + "4" * 40)
    amount = 5000
    
    # Mock token contract calls
    mock_contract = MagicMock()
    mock_contract.functions.nonces.return_value.call.return_value = 0
    mock_contract.functions.name.return_value.call.return_value = "USD Coin"
    client.w3.eth.contract = MagicMock(return_value=mock_contract)
    
    # Mock sign_typed_data
    mock_signed = MagicMock()
    mock_signed.v = 27
    mock_signed.r = b'\x01' * 32
    mock_signed.s = b'\x02' * 32
    client.account.sign_typed_data = MagicMock(return_value=mock_signed)
    
    result = client.sign_permit(token, spender, amount)
    
    assert result["v"] == 27
    assert len(result["r"]) == 32
    
    # Check primaryType
    structured_data = client.account.sign_typed_data.call_args[1]["full_message"]
    assert structured_data["primaryType"] == "Permit"
    assert structured_data["message"]["owner"] == client.account.address

def test_handle_402_decision_logic(client):
    """Checks if _handle_x402_v2 correctly switches between pay and pay_with_permit."""
    requirements = {
        'x402Version': 2,
        'orderId': "order123",
        'accepts': [{
            'type': 'onchain',
            'network': 'eip155:84532',
            'asset': "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0",
            'amount': '2000',
            'payTo': "0xMerchant",
            'router': "0xRouter"
        }]
    }
    
    # Case 1: Sufficient allowance -> calls pay
    with patch.object(client, '_get_allowance', return_value=5000), \
         patch.object(client, 'pay', return_value="0xHashPay") as mock_pay:
        client._handle_x402_v2("http://example.com", requirements)
        mock_pay.assert_called_once()
        
    # Case 2: Insufficient allowance -> calls pay_with_permit
    with patch.object(client, '_get_allowance', return_value=0), \
         patch.object(client, 'pay_with_permit', return_value="0xHashPermit") as mock_permit:
        client._handle_x402_v2("http://example.com", requirements)
        mock_permit.assert_called_once()
