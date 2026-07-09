"""Vercel build hook: copy templates + static into bundled directories."""
import shutil, os

ROOT = os.path.dirname(os.path.abspath(__file__))

# Templates → api/templates/ (bundled by @vercel/python because it's beside the entrypoint)
src = os.path.join(ROOT, "nse", "templates")
dst = os.path.join(ROOT, "api", "templates")
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(src, dst)
print(f"build: copied templates → api/templates/ ({sum(1 for _ in os.walk(dst) for __ in _[2])} files)")

# Static → public/static/ (served by Vercel's CDN, not Flask)
static_src = os.path.join(ROOT, "nse", "static")
public_dst = os.path.join(ROOT, "public", "static")
if os.path.exists(public_dst):
    shutil.rmtree(public_dst)
shutil.copytree(static_src, public_dst)
print(f"build: copied static → public/static/")
