import os
import logging
from paynode_sdk import PayNodeAgentClient # sdk-python repository
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging for visibility into PayNode's autonomous payment loop
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("paynode_demo")

# PayNode Agent Demo (Base Sepolia)
#
# To run this demo:
# 1. Install dependencies: pip install paynode-sdk-python requests web3 python-dotenv
# 2. Setup your .env file
# 3. Run: python examples/agent_client.py

# Configuration
TESTNET_RPC = os.getenv("PAYNODE_RPC_URL", "https://sepolia.base.org")
PRIVATE_KEY = os.getenv("CLIENT_PRIVATE_KEY", "0xYourTestnetPrivateKeyHere")
MERCHANT_URL = os.getenv("TARGET_MERCHANT_URL", "http://localhost:8000/api/premium-python-data")

def run_agent_demo():
    """
    Simulates an AI Agent requesting data from a PayNode-protected server.
    The Client will:
    1. Send a request to the protected resource.
    2. Receive a 402 'Payment Required' with amount, merchant, and order details.
    3. Automatically check the wallet balance and allowance.
    4. Sign and send an on-chain transaction (with EIP-2612 Permit-First strategy).
    5. Retry the original request with the new transaction hash (receipt) in headers.
    6. Return the ultimate 200 Success response.
    """
    
    logger.info("Initializing PayNode Agent Client...")
    
    # Instance PayNode Client and provide our testnet credentials
    agent = PayNodeAgentClient(
        private_key=PRIVATE_KEY, 
        rpc_urls=[TESTNET_RPC, "https://base-sepolia.publicnode.com"] # Failover RPCs
    )
    
    logger.info(f"Agent Wallet: {agent.account.address}")
    
    # 🎯 Single Get call: This handles the entire 402 logic internally
    logger.info(f"Requesting data from: {MERCHANT_URL}...")
    
    try:
        response = agent.get(MERCHANT_URL)
        
        # 🎊 If we've reached here, the payment was successful!
        if response.status_code == 200:
            data = response.json()
            logger.info("🎉 SUCCESS! Premium Data Received:")
            logger.info(f"Message: {data['data']['message']}")
            logger.info(f"Secret: {data['data']['secret_code']}")
            logger.info(f"Transaction ID: {data['payment_info']['receipt']}")
        else:
            logger.error(f"❌ Failed to reach service. Status: {response.status_code}")
            logger.debug(response.text)

    except Exception as e:
        logger.error(f"❌ Agent error: {str(e)}")

if __name__ == "__main__":
    run_agent_demo()
