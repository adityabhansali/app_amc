"""Vercel serverless entrypoint."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nse import create_app
app = create_app()
