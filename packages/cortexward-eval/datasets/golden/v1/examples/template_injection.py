"""A deliberately vulnerable, authored example for the golden benchmark dataset.

CWE-79: Server-Side Template Injection — a Flask request value is
interpolated directly into a Jinja template string before rendering.
"""

from flask import render_template_string, request


def greet():
    name = request.args.get("name")
    return render_template_string("Hello " + name)
