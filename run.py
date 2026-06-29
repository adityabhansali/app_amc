import os
import sys

# When launched by the *system* Python (e.g. the preview sandbox, which cannot
# read this project's .venv interpreter), make the venv's installed packages
# importable. Harmless no-op when already running inside the venv.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _ver in ("python3.9", "python3.10", "python3.11", "python3.12"):
    _sp = os.path.join(_HERE, ".venv", "lib", _ver, "site-packages")
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

from nse import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "5055"))
    app.run(host="0.0.0.0", port=port, debug=True)
