import requests
import time
from web3 import Web3
from eth_account import Account

# --- Configuration (Matching Anvil Deployment) ---
RPC_URL = "http://localhost:8545"
TARGET_URL = "http://localhost:3000/api/pom"
# Anvil default account #0 private key
PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

# Minimal ABIs
ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]
ROUTER_ABI = [
    {"inputs": [{"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}], "name": "pay", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

def run_pom_agent():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = Account.from_key(PRIVATE_KEY)
    print(f"🤖 AI Agent Active: {account.address}")

    # 1. Initial Request (Will fail with 402)
    print(f"🚀 Sending request to {TARGET_URL}...")
    payload = {"agent_name": "PayNode-Cyber-Agent", "message": "I am paying for access."}
    response = requests.post(TARGET_URL, json=payload)

    if response.status_code == 402:
        print("💡 Received 402 Payment Required. Parsing headers...")
        headers = response.headers
        
        contract_addr = headers.get('x-paynode-contract')
        merchant_addr = headers.get('x-paynode-merchant')
        amount = int(headers.get('x-paynode-amount'))
        token_addr = headers.get('x-paynode-token-address')
        order_id_str = headers.get('x-paynode-order-id')
        order_id_bytes = w3.keccak(text=order_id_str)

        print(f"💰 Required: {amount / 10**6} USDC to {merchant_addr}")

        # 2. Chain Pay Flow
        # A. Approve
        print("🔑 Approving MockUSDC...")
        token_contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        nonce = w3.eth.get_transaction_count(account.address)
        
        approve_tx = token_contract.functions.approve(contract_addr, amount).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': w3.to_wei('2', 'gwei')
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        tx_hash_approve = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        w3.eth.wait_for_transaction_receipt(tx_hash_approve)
        print(f"✅ Approved! (tx: {tx_hash_approve.hex()})")

        # B. Pay
        print("💸 Executing PayNodeRouter.pay()...")
        router_contract = w3.eth.contract(address=contract_addr, abi=ROUTER_ABI)
        pay_tx = router_contract.functions.pay(token_addr, merchant_addr, amount, order_id_bytes).build_transaction({
            'from': account.address,
            'nonce': nonce + 1,
            'gas': 200000,
            'gasPrice': w3.to_wei('2', 'gwei')
        })
        signed_pay = w3.eth.account.sign_transaction(pay_tx, PRIVATE_KEY)
        tx_hash_pay = w3.eth.send_raw_transaction(signed_pay.raw_transaction)
        print(f"⏳ Waiting for receipt: {tx_hash_pay.hex()}")
        w3.eth.wait_for_transaction_receipt(tx_hash_pay)
        print("✅ Payment Complete!")

        # 3. Retry Request with Receipt
        print("🔄 Retrying original request with x-paynode-receipt...")
        retry_headers = {
            'x-paynode-receipt': tx_hash_pay.hex(),
            'x-paynode-order-id': order_id_str
        }
        success_response = requests.post(TARGET_URL, json=payload, headers=retry_headers)
        
        if success_response.status_code == 200:
            print(f"🎊 SUCCESS! Server Response: {success_response.json()}")
        else:
            print(f"❌ Error during retry: {success_response.status_code} - {success_response.text}")

    elif response.status_code == 200:
        print("🎉 Request already paid and accepted!")
    else:
        print(f"❓ Unexpected status: {response.status_code} - {response.text}")

if __name__ == "__main__":
    run_pom_agent()
