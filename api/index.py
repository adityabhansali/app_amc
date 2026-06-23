"""Vercel serverless entrypoint.

Vercel's @vercel/python runtime serves the module-level WSGI `app` object.
All routes are funneled here by vercel.json, so this single function backs the
whole Flask application (public site, portal, ops console, chat, static files).
"""
import os
import sys

# Ensure the project root is importable so `import nse` resolves when this file
# is executed from the api/ directory inside the Vercel build.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse import create_app

app = create_app()
