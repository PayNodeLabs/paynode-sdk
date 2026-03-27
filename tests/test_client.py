import pytest
import responses
import base64
import json
from unittest.mock import MagicMock, patch
from paynode_sdk import PayNodeAgentClient, PayNodeException, ErrorCode

# Standard Base Sepolia Mock Values
MOCK_PRIVATE_KEY = "0x" + "1" * 64
MOCK_RPC = "https://sepolia.base.org"
MOCK_MERCHANT = "0x" + "7" * 40
MOCK_TOKEN = "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0"
MOCK_ROUTER = "0x" + "9" * 40
MOCK_ORDER_ID = "order_12345"
MOCK_TX_HASH = "0x6f3e1a0000000000000000000000000000000000000000000000000000000000"

@pytest.fixture
def client():
    """Returns a client with mocked W3 to avoid network errors during init."""
    with patch('paynode_sdk.client.Web3') as mock_w3:
        mock_instance = mock_w3.return_value
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 84532 # Base Sepolia
        mock_instance.eth.account.from_key.return_value.address = "0xAgentWalletAddress"
        return PayNodeAgentClient(MOCK_PRIVATE_KEY, MOCK_RPC)

@responses.activate
def test_402_v2_onchain_handshake(client):
    """
    Simulates a 402 with X-402-Required header (On-chain path).
    """
    target_url = "http://api.agent/secure"
    
    v2_req = {
        "x402Version": 2,
        "accepts": [{
            "type": "onchain",
            "network": "eip155:84532",
            "amount": "2000",
            "asset": MOCK_TOKEN,
            "payTo": MOCK_MERCHANT,
            "router": MOCK_ROUTER
        }]
    }
    b64_req = base64.b64encode(json.dumps(v2_req).encode()).decode()

    # 1. Mock the 402 response
    responses.add(
        responses.GET, target_url,
        headers={
            'X-402-Required': b64_req,
            'X-402-Order-Id': MOCK_ORDER_ID
        },
        status=402
    )
    
    # 2. Mock a successful subsequent request
    responses.add(
        responses.GET, target_url,
        status=200,
        json={"data": "Premium Secret Content"}
    )
    
    # 3. Patch the on-chain payment logic
    with patch.object(client, 'pay', return_value=MOCK_TX_HASH) as mock_pay, \
         patch.object(client, '_get_allowance', return_value=1000000): # Already has allowance
        
        response = client.get(target_url)
        
        # Verify result
        assert response.status_code == 200
        assert response.json()["data"] == "Premium Secret Content"
        
        # Verify PAYMENT-SIGNATURE was sent
        retry_request = responses.calls[1].request
        assert 'PAYMENT-SIGNATURE' in retry_request.headers
        payload = json.loads(base64.b64decode(retry_request.headers['PAYMENT-SIGNATURE']).decode())
        assert payload['x402Version'] == 2
        assert payload['_paynode']['type'] == 'onchain'
        assert payload['payload']['txHash'] == MOCK_TX_HASH

def test_dust_limit_protection(client):
    """Ensures the client throws an exception for payments < 0.001 USDC."""
    v2_req = {
        "x402Version": 2,
        "accepts": [{
            "type": "onchain",
            "network": "eip155:84532",
            "amount": "500", # Below 1000 limit
            "asset": MOCK_TOKEN,
            "payTo": MOCK_MERCHANT,
            "router": MOCK_ROUTER
        }]
    }
    
    with pytest.raises(PayNodeException) as exc:
        client._handle_x402_v2("http://example.com", v2_req)
    assert exc.value.code == ErrorCode.amount_too_low

def test_rpc_failover_logic():
    """
    Ensures the client automatically fails over to the second RPC 
    if the first one is unresponsive.
    """
    bad_rpc = "https://broken.rpc"
    good_rpc = "https://working.rpc"
    
    with patch('paynode_sdk.client.Web3') as mock_w3:
        # First call to is_connected() fails, second succeeds
        mock_w3.return_value.is_connected.side_effect = [False, True]
        mock_w3.return_value.eth.account.from_key.return_value.address = "0xAddr"
        
        client = PayNodeAgentClient(MOCK_PRIVATE_KEY, [bad_rpc, good_rpc])
        assert client.rpc_urls[0] == bad_rpc
        assert mock_w3.call_count == 2 # Called for both RPCs

@responses.activate
def test_insufficient_funds_on_chain(client):
    """Mocks on-chain failure (e.g. out of gas) and verifies exception handling."""
    target_url = "http://api.agent/secure"
    responses.add(responses.GET, target_url, status=402, headers={
        'X-402-Required': base64.b64encode(json.dumps({
            "x402Version": 2,
            "accepts": [{
                "type": "onchain",
                "network": "eip155:84532",
                "amount": "2000",
                "asset": MOCK_TOKEN,
                "payTo": MOCK_MERCHANT,
                "router": MOCK_ROUTER
            }]
        }).encode()).decode(),
        'X-402-Order-Id': MOCK_ORDER_ID
    })

    with patch.object(client, '_get_allowance', return_value=1000000), \
         patch.object(client, 'pay', side_effect=PayNodeException(ErrorCode.transaction_failed)), \
         patch.object(client, 'pay_with_permit', side_effect=PayNodeException(ErrorCode.transaction_failed)):
        
        with pytest.raises(PayNodeException) as exc:
            client.get(target_url)
        assert exc.value.code == ErrorCode.transaction_failed

@responses.activate
def test_402_v2_eip3009_handshake(client):
    """
    Simulates an EIP-3009 payment path via X-402-Required header.
    """
    target_url = "http://api.agent/v2/secure"
    
    v2_req = {
        "x402Version": 2,
        "accepts": [
            {
                "type": "eip3009",
                "network": "eip155:84532",
                "amount": "3000",
                "asset": MOCK_TOKEN,
                "payTo": MOCK_MERCHANT,
                "extra": {"name": "USD Coin", "version": "2"}
            }
        ]
    }
    b64_req = base64.b64encode(json.dumps(v2_req).encode()).decode()

    # 1. Mock the 402 response
    responses.add(
        responses.GET, target_url,
        status=402,
        headers={'X-402-Required': b64_req, 'X-402-Order-Id': 'v2-order'}
    )
    
    # 2. Mock success response
    responses.add(
        responses.GET, target_url,
        status=200,
        json={"data": "v2 secret"}
    )
    
    # 3. Patch the signing logic
    with patch.object(client, 'sign_transfer_with_authorization', return_value={"signature": "0xsig", "authorization": {}}) as mock_sign:
        response = client.get(target_url)
        
        assert response.status_code == 200
        assert mock_sign.called
        
        # Verify PAYMENT-SIGNATURE
        retry_request = responses.calls[1].request
        assert 'PAYMENT-SIGNATURE' in retry_request.headers
        payload = json.loads(base64.b64decode(retry_request.headers['PAYMENT-SIGNATURE']).decode())
        assert payload['x402Version'] == 2
        assert payload['_paynode']['type'] == 'eip3009'
        assert payload['payload']['signature'] == '0xsig'

@responses.activate
def test_settlement_confirmation_logging(client):
    """
    Ensures the client correctly reads and logs the PAYMENT-RESPONSE header.
    """
    target_url = "http://api.agent/settle"
    
    # 1. Mock the 402 response
    v2_req = {
        "x402Version": 2,
        "accepts": [{"type": "onchain", "network": "eip155:84532", "amount": "1000", "asset": MOCK_TOKEN, "payTo": MOCK_MERCHANT, "router": MOCK_ROUTER}]
    }
    b64_req = base64.b64encode(json.dumps(v2_req).encode()).decode()
    responses.add(responses.GET, target_url, status=402, headers={'X-402-Required': b64_req})
    
    # 2. Mock settlement header in success response
    settle_data = {"success": True, "transaction": MOCK_TX_HASH}
    b64_settle = base64.b64encode(json.dumps(settle_data).encode()).decode()
    
    responses.add(
        responses.GET, target_url,
        status=200,
        headers={'PAYMENT-RESPONSE': b64_settle},
        json={"data": "OK"}
    )
    
    with patch.object(client, 'pay', return_value=MOCK_TX_HASH), \
         patch.object(client, '_get_allowance', return_value=1000000), \
         patch('paynode_sdk.client.logger') as mock_logger:
        
        response = client.get(target_url)
        assert response.status_code == 200
        
        # Verify logger was called with confirmation
        # Since logger.info is called directly from the module logger, we need to handle that.
        # But here we patched it specifically.
        mock_logger.info.assert_any_call(f"✅ [PayNode-PY] Settlement confirmed: {MOCK_TX_HASH}")
