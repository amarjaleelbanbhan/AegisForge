"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-918: Server-Side Request Forgery — a Flask request value flows
unsanitized into an outbound HTTP call.
"""

import requests
from flask import request


def fetch_avatar():
    url = request.args.get("url")
    return requests.get(url)
