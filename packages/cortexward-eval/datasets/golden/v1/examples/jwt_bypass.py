"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-347: Improper Verification of Cryptographic Signature — JWT signature
verification explicitly disabled.
"""

import jwt


def decode_token(token: str):
    return jwt.decode(token, options={"verify_signature": False})
