#!/data/data/com.termux/files/usr/bin/bash
# One-tap launcher for Termux:Widget. See README.md "Launching it with one
# tap" for setup. Guards against a double-tap starting a second APScheduler
# (duplicate snapshots/recurring runs) by checking for an already-running
# server before starting another.
set -e
cd "$(dirname "$0")/.."

if pgrep -f "python.*wsgi.py" > /dev/null; then
    echo "Build Steward is already running - open the app."
    sleep 2
    exit 0
fi

source .venv/bin/activate
export FLASK_APP=wsgi.py

echo "Starting Build Steward..."
echo "Open http://localhost:5055 (or tap the installed app icon) once it's up."
echo "Leave this Termux session open - closing it stops the server."
echo

python wsgi.py
