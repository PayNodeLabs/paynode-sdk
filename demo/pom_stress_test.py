import requests
import time
from web3 import Web3
from eth_account import Account

# --- Configuration ---
RPC_URL = "http://localhost:8545"
TARGET_URL = "http://localhost:3000/api/pom?network=testnet"
PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]
ROUTER_ABI = [
    {"inputs": [{"name": "token", "type": "address"}, {"name": "merchant", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "orderId", "type": "bytes32"}], "name": "pay", "outputs": [], "stateMutability": "nonpayable", "type": "function"}
]

AGENTS = [
    "Claude-3-Sniper",
    "GPT-4o-Vanguard",
    "Gemini-Pro-Explorer",
    "Llama-3-Titan",
    "Mistral-Large-Phantom"
]

def run_agent_workflow(w3, account, agent_name):
    print(f"\n--- 🤖 Agent: {agent_name} Starting Workflow ---")
    
    # 1. Handshake
    payload = {"agent_name": agent_name, "message": f"Hello from {agent_name}"}
    response = requests.post(TARGET_URL, json=payload)
    
    if response.status_code != 402:
        print(f"⚠️ Unexpected status: {response.status_code}")
        return False

    headers = response.headers
    contract_addr = headers.get('x-paynode-contract')
    merchant_addr = headers.get('x-paynode-merchant')
    amount = int(headers.get('x-paynode-amount'))
    token_addr = headers.get('x-paynode-token-address')
    order_id_str = headers.get('x-paynode-order-id')
    order_id_bytes = w3.keccak(text=order_id_str)

    # 2. Chain Pay
    nonce = w3.eth.get_transaction_count(account.address)
    
    # A. Approve (Simplified: always approve for demo purposes)
    token_contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
    approve_tx = token_contract.functions.approve(contract_addr, amount).build_transaction({
        'from': account.address, 'nonce': nonce, 'gas': 100000, 'gasPrice': w3.to_wei('2', 'gwei')
    })
    signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    
    # B. Pay
    router_contract = w3.eth.contract(address=contract_addr, abi=ROUTER_ABI)
    pay_tx = router_contract.functions.pay(token_addr, merchant_addr, amount, order_id_bytes).build_transaction({
        'from': account.address, 'nonce': nonce + 1, 'gas': 200000, 'gasPrice': w3.to_wei('2', 'gwei')
    })
    signed_pay = w3.eth.account.sign_transaction(pay_tx, PRIVATE_KEY)
    tx_hash_pay = w3.eth.send_raw_transaction(signed_pay.raw_transaction)
    
    print(f"💸 {agent_name} paid! Tx: {tx_hash_pay.hex()}")
    w3.eth.wait_for_transaction_receipt(tx_hash_pay)

    # 3. Retry with Receipt
    retry_headers = {'x-paynode-receipt': tx_hash_pay.hex(), 'x-paynode-order-id': order_id_str}
    success_response = requests.post(TARGET_URL, json=payload, headers=retry_headers)
    
    if success_response.status_code == 200:
        print(f"✅ {agent_name} verified!")
        return True
    else:
        print(f"❌ {agent_name} failed verification: {success_response.text}")
        return False

def stress_test():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = Account.from_key(PRIVATE_KEY)
    
    print("🚀 PAYNODE STRESS TEST INITIATED")
    print("--------------------------------")
    
    for round_num in range(3): # 3 rounds
        print(f"\n🌊 ROUND {round_num + 1} STARTING...")
        for agent in AGENTS:
            run_agent_workflow(w3, account, agent)
            time.sleep(1) # Small delay to see UI update
            
    print("\n🏁 STRESS TEST COMPLETE.")

if __name__ == "__main__":
    stress_test()
