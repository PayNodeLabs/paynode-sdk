import pytest
import responses
from unittest.mock import MagicMock, patch
from paynode_sdk import PayNodeAgentClient, PayNodeException, ErrorCode

# Standard Base Sepolia Mock Values
MOCK_PRIVATE_KEY = "0x" + "1" * 64
MOCK_RPC = "https://sepolia.base.org"
MOCK_MERCHANT = "0xMerchantWalletAddress789"
MOCK_TOKEN = "0x109AEddD656Ed2761d1e210E179329105039c784"
MOCK_ROUTER = "0xPayNodeRouterAddress123"
MOCK_ORDER_ID = "order_12345"
MOCK_TX_HASH = "0x6f3e1a..."

@pytest.fixture
def client():
    """Returns a client with mocked W3 to avoid network errors during init."""
    with patch('paynode_sdk.client.Web3') as mock_w3:
        mock_w3.return_value.is_connected.return_value = True
        mock_w3.return_value.eth.account.from_key.return_value.address = "0xAgentWalletAddress"
        return PayNodeAgentClient(MOCK_PRIVATE_KEY, MOCK_RPC)

@responses.activate
def test_402_handshake_parsing(client):
    """
    Simulates a 402 'Payment Required' response from a server.
    Ensures the client correctly extracts metadata from custom PayNode headers.
    """
    target_url = "http://api.agent/secure"
    
    # 1. Mock the 402 response
    responses.add(
        responses.GET, target_url,
        headers={
            'x-paynode-contract': MOCK_ROUTER,
            'x-paynode-merchant': MOCK_MERCHANT,
            'x-paynode-amount': '2000', # 0.002 USDC
            'x-paynode-token-address': MOCK_TOKEN,
            'x-paynode-order-id': MOCK_ORDER_ID,
            'x-paynode-chain-id': '84532'
        },
        status=402,
        json={"error": "Payment Required"}
    )
    
    # 2. Mock a successful subsequent request (after payment)
    responses.add(
        responses.GET, target_url,
        status=200,
        json={"data": "Premium Secret Content"}
    )
    
    # 3. Patch the on-chain payment logic to just return a fake TxHash
    with patch.object(client, 'pay_with_permit', return_value=MOCK_TX_HASH) as mock_pay, \
         patch.object(client, '_get_allowance', return_value=0): # Trigger permit
        
        response = client.get(target_url)
        
        # Verify result
        assert response.status_code == 200
        assert response.json()["data"] == "Premium Secret Content"
        
        # Verify 402 headers were correctly parsed and passed to pay method
        mock_pay.assert_called_once_with(MOCK_ROUTER, MOCK_TOKEN, MOCK_MERCHANT, 2000, MOCK_ORDER_ID)

def test_dust_limit_protection(client):
    """Ensures the client throws an exception for payments < 0.001 USDC."""
    headers = {
        'x-paynode-contract': MOCK_ROUTER,
        'x-paynode-merchant': MOCK_MERCHANT,
        'x-paynode-amount': '500', # Below 1000 limit
        'x-paynode-token-address': MOCK_TOKEN,
        'x-paynode-order-id': MOCK_ORDER_ID
    }
    
    with pytest.raises(PayNodeException) as exc:
        client._handle_402(headers)
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
    responses.add(responses.GET, target_url, status=402, headers={'x-paynode-amount': '2000', 'x-paynode-contract': MOCK_ROUTER, 'x-paynode-merchant': MOCK_MERCHANT, 'x-paynode-token-address': MOCK_TOKEN, 'x-paynode-order-id': MOCK_ORDER_ID})

    with patch.object(client, '_get_allowance', return_value=1000000), \
         patch.object(client, '_execute_pay', side_effect=Exception("Insufficient Funds")):
        
        with pytest.raises(PayNodeException) as exc:
            client.get(target_url)
        assert exc.value.code == ErrorCode.transaction_failed
