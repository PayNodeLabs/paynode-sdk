import asyncio
import pytest
from unittest.mock import MagicMock, patch
from paynode_sdk import PayNodeVerifier, ErrorCode

@pytest.fixture
def verifier():
    with patch('paynode_sdk.verifier.Web3') as mock_w3:
        mock_instance = mock_w3.return_value
        mock_instance.is_connected.return_value = True
        mock_instance.eth = MagicMock()
        return PayNodeVerifier(
            rpc_urls="http://localhost",
            contract_address="0x" + "a" * 40,
            chain_id=84532
        )

@pytest.mark.asyncio
async def test_concurrent_double_spend_eip3009(verifier):
    """
    Simultaneously triggers multiple verification requests with the same nonce.
    Ensures only ONE succeeds and the others fail with duplicate_transaction.
    """
    mock_from = "0x" + "b" * 40
    mock_to = "0x" + "c" * 40
    mock_nonce = "0x" + "d" * 64
    mock_amount = 2000
    mock_token = "0x65c088EfBDB0E03185Dbe8e258Ad0cf4Ab7946b0"

    payload = {
        "signature": "0x" + "1" * 130,
        "authorization": {
            "from": mock_from,
            "to": mock_to,
            "value": str(mock_amount),
            "validAfter": "0",
            "validBefore": "9999999999",
            "nonce": mock_nonce
        }
    }

    # 1. Mock Signature Recovery
    with patch('paynode_sdk.verifier.Account.recover_message') as mock_recover:
        mock_recover.return_value = mock_from

        # 2. Mock RPC State (Valid balance, Not used on-chain)
        # In verifier.py, these are called via token_contract.functions.X.call()
        mock_contract = MagicMock()
        mock_contract.functions.balanceOf().call.return_value = 5000
        mock_contract.functions.authorizationState().call.return_value = False
        verifier.w3.eth.contract.return_value = mock_contract

        # 3. Simulate High Concurrency (10 simultaneous requests)
        tasks = []
        for _ in range(10):
            tasks.append(verifier.verify_transfer_with_authorization(
                mock_token,
                payload,
                {"to": mock_to, "value": mock_amount}
            ))

        results = await asyncio.gather(*tasks)

        # 4. Analyze Results
        success_count = sum(1 for r in results if r["isValid"] is True)
        duplicate_count = sum(1 for r in results if (
            r["isValid"] is False and 
            r["error"].code == ErrorCode.duplicate_transaction
        ))

        # EXACTLY ONE should be valid
        assert success_count == 1, f"Expected 1 success, got {success_count}"
        # THE OTHER 9 should be duplicates
        assert duplicate_count == 9, f"Expected 9 duplicates, got {duplicate_count}"
        assert len(results) == 10
