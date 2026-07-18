"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-89: SQL Injection via string-formatted query construction.
"""


def find_user(cursor, username: str):
    query = "SELECT * FROM users WHERE username = '%s'" % username
    cursor.execute(query)
    return cursor.fetchone()
