#!/data/data/com.termux/files/usr/bin/bash
# One-tap launcher for Termux:Widget. See README.md "Launching it with one
# tap" for setup. Guards against a double-tap starting a second APScheduler
# (duplicate snapshots/recurring runs) by checking for an already-running
# server before starting another. If Termux:API is installed, also opens
# the installed app automatically once the server responds -- otherwise
# this just starts the server and you switch to the app by hand.
set -e
# NOT `cd "$(dirname "$0")/.."` -- when invoked through the ~/.shortcuts
# symlink, $0 is the path used to invoke it (~/.shortcuts/steward.sh), not
# where the symlink points, so that resolved to $HOME instead of the repo.
cd "$HOME/steward"

URL="http://127.0.0.1:5055"

# Polls the port with bash's built-in /dev/tcp (no curl dependency) and
# fires the Android "open URL" intent once something answers. Android
# routes that intent to the installed PWA, not a browser tab, because the
# PWA is registered as this URL's handler.
wait_for_server_then_open() {
    for _ in $(seq 1 40); do
        if (exec 3<>/dev/tcp/127.0.0.1/5055) 2>/dev/null; then
            exec 3<&- 3>&-
            termux-open-url "$URL"
            return
        fi
        sleep 0.25
    done
}

if pgrep -f "python.*wsgi.py" > /dev/null; then
    echo "Build Steward is already running."
    if command -v termux-open-url > /dev/null 2>&1; then
        termux-open-url "$URL"
    else
        echo "Open $URL (or tap the installed app icon)."
    fi
    sleep 1
    exit 0
fi

source .venv/bin/activate
export FLASK_APP=wsgi.py

# Set a copy aside on internal shared storage before starting. This lives
# outside Termux's private directory, so it survives uninstalling Termux --
# and other apps (Drive, Syncthing) can see it to carry it off the device.
# Needs `termux-setup-storage` once to grant the permission.
#
# Never allowed to block the launch: `|| true` because `set -e` is on, and a
# missing SD path or denied permission must not stop you opening the app.
BACKUP_DIR="/sdcard/Steward/backup"
if [ -w /sdcard ]; then
    flask backup "$BACKUP_DIR" --keep 14 || echo "  (backup skipped - see above)"
else
    echo "  (no access to /sdcard - run termux-setup-storage to enable backups)"
fi

echo "Starting Build Steward..."
if command -v termux-open-url > /dev/null 2>&1; then
    echo "Will open the app automatically once it's ready."
    wait_for_server_then_open &
else
    echo "Open $URL (or tap the installed app icon) once it's up."
    echo "Tip: install Termux:API to have this open automatically - see README."
fi
echo "Leave this Termux session open - closing it stops the server."
echo

python wsgi.py
