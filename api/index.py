"""Vercel serverless entrypoint.

Vercel's @vercel/python runtime serves the module-level WSGI `app` object.
All routes are funneled here by vercel.json, so this single function backs the
whole Flask application (public site, portal, ops console, chat, static files).
"""
import os
import sys

# Ensure the project root is importable so `import nse` resolves when this file
# is executed from the api/ directory inside the Vercel build.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from nse import create_app
    app = create_app()
except Exception as exc:
    # Catch startup errors so Vercel returns a readable 500 instead of a
    # silent 404.  Once stable, remove this and use `from nse import create_app;
    # app = create_app()` directly.
    from flask import Flask, Response

    _err = Flask(__name__)

    @_err.route("/", defaults={"path": ""}, methods=["GET", "POST"])
    @_err.route("/<path:path>")
    def _fallback(path):
        return Response(
            f"<h2>NSE App startup error</h2><pre>{exc}</pre>",
            status=500,
            mimetype="text/html",
        )

    app = _err
