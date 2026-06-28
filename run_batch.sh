#!/bin/bash
# =============================================================================
#   PixelPitch — one-command background image generation
# =============================================================================
# Ensures the dedicated debug Chrome is running, then runs the CDP agent on one
# Markdown batch file. The agent drives a BACKGROUND tab via trusted CDP input,
# so it never touches your keyboard/mouse — keep working while it runs.
#
# USAGE:
#   ./run_batch.sh <batch.md> [--bg]
#     <batch.md>  a single MD file of numbered prompts (e.g. batches/batch_1.md)
#     --bg        run detached in the background (logs to <batch>.log)
#
# SETTINGS (env vars, optional):
#   MODEL (default "Nano Banana Pro")  QUALITY (1K|2K|4K, default 2K)
#   ASPECT (default 9:16)              UNLIMITED (on|off, default on)
#   WAIT (seconds between images, default 50)
#
# EXAMPLES:
#   ./run_batch.sh batches/batch_1.md                 # run batch 1 (foreground log)
#   ./run_batch.sh batches/batch_2.md --bg            # run batch 2 detached
#   QUALITY=4K ./run_batch.sh batches/batch_1.md --bg # 4K, detached
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH_FILE="${1:?Usage: ./run_batch.sh <batch.md> [--bg]}"
MODE="${2:-}"
PORT="${PORT:-9222}"

# default settings (overridable via env)
export MODEL="${MODEL:-Nano Banana Pro}"
export QUALITY="${QUALITY:-2K}"
export ASPECT="${ASPECT:-9:16}"
export UNLIMITED="${UNLIMITED:-on}"
export WAIT="${WAIT:-50}"
export PORT

[[ -f "$BATCH_FILE" ]] || { echo "ERROR: batch file not found: $BATCH_FILE"; exit 1; }

# pick a Node with built-in WebSocket (>=22)
pick_node() {
  for v in v25 v24 v22; do
    local p
    p=$(ls -d "$HOME"/.nvm/versions/node/${v}* 2>/dev/null | sort -V | tail -1)
    [[ -n "$p" && -x "$p/bin/node" ]] && { echo "$p/bin/node"; return; }
  done
  command -v node
}
NODE="$(pick_node)"

# ensure the debug Chrome is up
"$SCRIPT_DIR/start_chrome_debug.sh" "$PORT"

if [[ "$MODE" == "--bg" ]]; then
  LOG="${BATCH_FILE%.md}.log"
  echo "Running in background. Logs -> $LOG"
  nohup "$NODE" "$SCRIPT_DIR/cdp_agent.js" "$BATCH_FILE" >"$LOG" 2>&1 &
  echo "PID $!  —  tail -f \"$LOG\" to watch."
else
  "$NODE" "$SCRIPT_DIR/cdp_agent.js" "$BATCH_FILE"
fi
