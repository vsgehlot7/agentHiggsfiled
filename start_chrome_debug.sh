#!/bin/bash
# Launch a DEDICATED Chrome instance with the DevTools remote-debugging port on.
#
# Why a separate profile?  Chrome 136+ refuses to enable remote debugging on
# your normal (default) profile for security. So we use an isolated profile in
# ~/.chrome-pixelpitch. Your MAIN Chrome (with all your work tabs) is untouched.
#
# One-time: log into Higgsfield in the debug window that opens, then leave it.
# The CDP agent (cdp_agent.js) drives a BACKGROUND tab there with trusted input,
# so it never steals your keyboard/mouse — you can keep working in your main Chrome.

set -euo pipefail
PORT="${1:-9222}"
PROFILE="${CHROME_DEBUG_PROFILE:-$HOME/.chrome-pixelpitch}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
START_URL="https://higgsfield.ai/ai/image?model=nano-banana-pro"

if curl -s --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "Debug Chrome already running on port ${PORT}."
  exit 0
fi

mkdir -p "$PROFILE"
echo "Launching dedicated debug Chrome (profile: $PROFILE) on port ${PORT}..."
"$CHROME" \
  --user-data-dir="$PROFILE" \
  --remote-debugging-port="${PORT}" \
  --no-first-run --no-default-browser-check \
  "$START_URL" >/dev/null 2>&1 &

for i in $(seq 1 30); do
  if curl -s --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "Debug port ${PORT} ready."
    echo "If this is the first run, LOG IN to Higgsfield in the new window, then keep it open."
    exit 0
  fi
  sleep 0.5
done
echo "ERROR: debug port did not come up." >&2
exit 1
