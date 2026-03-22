import os
import sys
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# Add parent dir to sys.path to import paynode_sdk
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paynode_sdk.client import PayNodeAgentClient

load_dotenv()

# Configuration
RPC_URL = os.getenv("RPC_URL", "https://sepolia.base.org")
PRIVATE_KEY = os.getenv("CLIENT_PRIVATE_KEY")
MOCK_USDC_ADDR = "0xeAC1f2C7099CdaFfB91Aa3b8Ffd653Ef16935798"

if not PRIVATE_KEY:
    print("❌ Error: CLIENT_PRIVATE_KEY not found in .env")
    sys.exit(1)

def main():
    client = PayNodeAgentClient(PRIVATE_KEY, [RPC_URL])
    account = Account.from_key(PRIVATE_KEY)
    
    print(f"💰 Connecting to {RPC_URL}...")
    print(f"🔗 Minting for address: {account.address}")

    # Minimal Mintable ERC20 ABI
    abi = [{"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
    usdc = client.w3.eth.contract(address=MOCK_USDC_ADDR, abi=abi)

    # Mint 1,000 USDC (6 decimals)
    amount = 1000 * 10**6
    
    print("⏳ Sending mint transaction...")
    tx = usdc.functions.mint(account.address, amount).build_transaction({
        'from': account.address,
        'nonce': client.w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': int(client.w3.eth.gas_price * 1.2)
    })
    
    signed_tx = account.sign_transaction(tx)
    tx_hash = client.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"🚀 Mint Transaction Sent! Hash: {client.w3.to_hex(tx_hash)}")
    print("⏳ Waiting for confirmation...")
    
    receipt = client.w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status == 1:
        print("✅ SUCCESS: You now have 1,000 Test USDC!")
    else:
        print("❌ FAILED: Minting failed. Check Basescan.")

if __name__ == "__main__":
    main()
