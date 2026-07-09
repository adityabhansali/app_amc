"""Vercel serverless entrypoint."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _make_app():
    from nse import create_app
    return create_app()


try:
    _result = _make_app()
except Exception as exc:
    import traceback
    from flask import Flask, Response
    _err = Flask(__name__)

    @_err.route("/", defaults={"path": ""})
    @_err.route("/<path:path>")
    def _fallback(path):
        tb = traceback.format_exc()
        return Response(
            f"<h2>NSE App startup error</h2><pre>{exc}\n\n{tb}</pre>",
            status=500,
            mimetype="text/html",
        )

    _result = _err

app = _result
