"""ASGI entry point for uvicorn.

The factory lives in `paperproof.api.factory` so tests can import it without
creating the default data directory.
"""

from paperproof.api.factory import create_app

app = create_app()
