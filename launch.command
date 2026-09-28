#!/bin/bash
# SUFS Reimbursement Agent — double-click launcher (macOS)
#   1) Launches the remote-debugging "SUFS Chrome" profile (needed for auto-fill / PDF download)
#   2) Starts the local web app
#   3) Opens the app UI as a tab in that same Chrome window
# The HTTP port comes from the shared registry (shared/ports.py); $PORT overrides.

# This script lives in the project folder, so it finds the project wherever it is.
PROJECT="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SUFS_PROFILE="$HOME/.sufs-agent-chrome"
DEBUG_PORT=9222

cd "$PROJECT" || { echo "Could not find project folder: $PROJECT"; read -r; exit 1; }

# Resolve the app port from the shared registry (same source of truth as main.py).
PORT="$(.venv/bin/python - <<'PY' 2>/dev/null
import os, sys
from pathlib import Path
val = None
for parent in Path.cwd().resolve().parents:
    if (parent / "shared" / "ports.py").exists():
        sys.path.insert(0, str(parent / "shared"))
        try:
            from ports import get_port
            val = get_port("step_up_tool", default=5054)
        except Exception:
            val = None
        break
print(val if val is not None else os.environ.get("PORT", 5054))
PY
)"
[ -z "$PORT" ] && PORT=5054
URL="http://127.0.0.1:${PORT}"

# Launch (or reuse) the SUFS debugging Chrome, optionally opening a URL in it.
sufs_chrome() {
  "$CHROME" --remote-debugging-port="$DEBUG_PORT" --user-data-dir="$SUFS_PROFILE" "$@" >/dev/null 2>&1 &
}

# Open the app URL: in the SUFS Chrome if Chrome exists, else the default browser.
open_app() {
  if [ -x "$CHROME" ]; then sufs_chrome "$URL"; else open "$URL"; fi
}

# True only if *our* app (not some other server) is answering on the port.
sufs_up() { curl -s "$URL/" 2>/dev/null | grep -q "SUFS Reimbursement Agent"; }

# --- 1) SUFS remote-debugging Chrome ---------------------------------------
if curl -s -o /dev/null "http://127.0.0.1:${DEBUG_PORT}/json/version"; then
  echo "SUFS Chrome (debugging) already running."
elif [ -x "$CHROME" ]; then
  echo "Launching SUFS Chrome (remote debugging) …"
  sufs_chrome
else
  echo "WARNING: Google Chrome not found at:"
  echo "  $CHROME"
  echo "Skipping debugging-Chrome launch — auto-fill / PDF download won't work until it's running."
fi

# --- 2/3) Start the app, then open it in Chrome ----------------------------
# Already running (and it's really SUFS)? Just open it.
if sufs_up; then
  echo "SUFS app already running on port $PORT — opening it."
  open_app
  exit 0
fi

# Port is busy but it's NOT the SUFS app — don't open the wrong thing.
if curl -s -o /dev/null "$URL/" 2>/dev/null; then
  echo "WARNING: port $PORT is in use by a different app (not SUFS)."
  echo "Free that port, or set a different one in shared/ports.py, then try again."
  read -r
  exit 1
fi

# When OUR server responds, open the app tab (background watcher).
(
  for _ in $(seq 1 40); do
    sleep 0.5
    if sufs_up; then open_app; break; fi
  done
) &

echo "Starting the SUFS Reimbursement Agent on port $PORT …"
echo "(Leave this window open while you work. Close it or press Ctrl-C to stop the app.)"
echo
.venv/bin/python main.py

echo
echo "App stopped. Press Return to close this window."
read -r
