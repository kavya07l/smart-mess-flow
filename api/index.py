"""Expose the Flask application as a Vercel Python Function."""

import os

# Vercel functions can only write to the temporary directory.
os.environ.setdefault("MESS_DATABASE", "/tmp/smart-mess-flow.db")

from app import app
