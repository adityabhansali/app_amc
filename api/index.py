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
    _startup_error = str(exc)
    _startup_tb = traceback.format_exc()
    from flask import Flask, Response

    _err = Flask(__name__)

    @_err.route("/", defaults={"path": ""})
    @_err.route("/<path:path>")
    def _fallback(path):
        return Response(
            f"<h2>NSE App startup error</h2><pre>{_startup_error}\n\n{_startup_tb}</pre>",
            status=500,
            mimetype="text/html",
        )

    _result = _err

app = _result

# TEMP debug: verify template paths on Vercel
@app.route("/_debug/paths")
def _debug_paths():
    import flask
    a = flask.current_app._get_current_object()
    info = {
        "ROOT": ROOT,
        "template_folder": a.template_folder,
        "static_folder": a.static_folder,
        "api_templates_exists": os.path.isdir(os.path.join(ROOT, "api", "templates")),
        "nse_templates_exists": os.path.isdir(os.path.join(ROOT, "nse", "templates")),
    }
    tpl_dir = a.template_folder
    if tpl_dir and os.path.isdir(tpl_dir):
        all_files = [os.path.relpath(os.path.join(dp, fn), tpl_dir)
                     for dp, _, fns in os.walk(tpl_dir) for fn in fns]
        info["template_files"] = sorted(all_files)[:30]
        info["template_count"] = len(all_files)
    else:
        info["template_files"] = "DIR NOT FOUND"
    # list api/ directory
    api_dir = os.path.join(ROOT, "api")
    if os.path.isdir(api_dir):
        info["api_dir_contents"] = sorted(os.listdir(api_dir))
    # list nse/ directory top-level
    nse_dir = os.path.join(ROOT, "nse")
    if os.path.isdir(nse_dir):
        info["nse_dir_contents"] = sorted(os.listdir(nse_dir))
    from flask import jsonify
    return jsonify(info)
