"""WSGI entry point.  Run with:  flask --app wsgi run

Run directly (``python wsgi.py``) to start the dev server on ``$PORT``; the
Flask CLI only reads ``FLASK_RUN_PORT``, so this is what lets a launcher hand
us an arbitrary free port. Falls back to 5055.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("FLASK_RUN_PORT") or 5055)
    app.run(host="127.0.0.1", port=port, debug=True)
