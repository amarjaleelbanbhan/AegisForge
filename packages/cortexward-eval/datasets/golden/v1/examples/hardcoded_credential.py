"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-798: Use of Hard-coded Credentials.
"""

DATABASE_PASSWORD = "Sup3rS3cretPassw0rd!"


def connect():
    return {"password": DATABASE_PASSWORD}
