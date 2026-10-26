"""Expose the Flask application as a Vercel Python Function."""

import os
import tempfile

# Vercel's temporary directory is writable and available as /tmp.
os.environ.setdefault(
    "MESS_DATABASE",
    os.path.join(tempfile.gettempdir(), "smart-mess-flow.db"),
)

from app import app
