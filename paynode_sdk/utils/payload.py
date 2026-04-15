import base64
import json
import logging
from typing import Optional, Dict, Any
from ..constants import SDK_VERSION

logger = logging.getLogger("paynode_sdk.payload")

class PayNodePayloadHelper:
    """
    Normalizes raw payment payloads into the Unified format.
    Mirrors JS X402PayloadHelper.
    """
    
    @staticmethod
    def normalize(auth_header: str, fallback_order_id: str = "") -> Dict[str, Any]:
        """
        Normalizes a raw payment payload (from PAYMENT-SIGNATURE or X-402-Payload headers).
        """
        try:
            decoded = base64.b64decode(auth_header).decode('utf-8')
            parsed = json.loads(decoded)

            # 1. Handle Official X402 V2 Standard Format
            if parsed.get('x402Version') == 2 and parsed.get('accepted'):
                inferred_type = "onchain"
                payload_content = parsed.get('payload', {})
                
                if payload_content.get('signature') or payload_content.get('authorization'):
                    inferred_type = "eip3009"
                elif payload_content.get('txHash'):
                    inferred_type = "onchain"

                return {
                    "x402Version": 2,
                    "type": parsed.get('_paynode', {}).get('type') or inferred_type,
                    "orderId": parsed.get('_paynode', {}).get('orderId') or fallback_order_id,
                    "router": parsed.get('accepted', {}).get('router') or parsed.get('router'),
                    "payload": parsed.get('payload'),
                    "_paynode": {
                        "sdkVersion": SDK_VERSION
                    }
                }

            # 2. Handle Legacy or already Unified Format
            version = parsed.get('version')
            if isinstance(version, str) and (version.startswith("2.2") or version.startswith("2.3") or version.startswith("2.4")):
                return {
                    "x402Version": parsed.get('x402Version', 2),
                    "type": parsed.get('type'),
                    "orderId": parsed.get('orderId') or parsed.get('order_id') or fallback_order_id,
                    "router": parsed.get('router'),
                    "payload": parsed.get('payload'),
                    "_paynode": parsed.get('_paynode') or {
                        "sdkVersion": version
                    }
                }

            # 3. Fallback
            return parsed
            
        except Exception as e:
            logger.error(f"Failed to normalize PayNode payload: {e}")
            raise ValueError(f"Failed to normalize PayNode payload: {e}")
