"""A deliberately clean, authored example for the golden benchmark dataset.

A true-negative counterpart to sql_injection.py: the semantically
equivalent, safe way to do the same thing (a parameterized query).
Expected findings: none.
"""


def find_user(cursor, username: str):
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    return cursor.fetchone()
