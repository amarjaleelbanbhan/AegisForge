"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-502: Deserialization of Untrusted Data via `pickle.loads`.
"""

import pickle


def load_session(raw_bytes: bytes):
    return pickle.loads(raw_bytes)
