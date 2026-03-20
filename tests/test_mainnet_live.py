import os
import requests
from dotenv import load_dotenv
from paynode_sdk.client import PayNodeAgentClient

load_dotenv()

"""
🚀 PAYNODE MAINNET LIVE TEST (PYTHON - FIXED)
--------------------------------------------
Performing a real POST request to trigger 402 handshake.
"""

def run_python_mainnet_test():
    private_key = os.getenv("PAYNODE_PRIVATE_KEY")
    rpc_url = os.getenv("BASE_MAINNET_RPC", "https://mainnet.base.org")
    target_url = "https://www.paynode.dev/api/pom?network=mainnet"

    if not private_key:
        print("❌ Error: PAYNODE_PRIVATE_KEY not found in .env")
        return

    print("🛠️ Initializing PayNode Python Client...")
    client = PayNodeAgentClient(
        rpc_urls=[rpc_url],
        private_key=private_key
    )

    print(f"📡 Sending POST request to protected API: {target_url}")

    try:
        # CHANGED: Use .post() to trigger the 402 payment required flow
        response = client.post(
            url=target_url,
            json={"agent_name": "Python-Mainnet-Explorer-Agent"}
        )

        result = response.json()
        if response.status_code == 200:
            print("✅ SUCCESS! Access Granted to Mainnet Resource.")
            print(f"📜 Merchant Message: {result.get('message')}")
            print(f"🔗 Transaction Hash: {result.get('txHash')}")
            print(f"🌍 View on Explorer: https://www.paynode.dev/pom")
        else:
            print(f"❌ Failed with status {response.status_code}: {result}")

    except Exception as e:
        print(f"❌ Execution Error: {str(e)}")

if __name__ == "__main__":
    run_python_mainnet_test()
