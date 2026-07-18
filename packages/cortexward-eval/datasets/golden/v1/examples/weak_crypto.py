"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-327: Use of a Broken or Risky Cryptographic Algorithm (MD5).
"""

import hashlib


def fingerprint(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()
