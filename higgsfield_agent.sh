#!/bin/bash
# =============================================================================
#   PixelPitch  —  Higgsfield Image Generation Agent
# =============================================================================
# Automates image generation on https://higgsfield.ai/ai/image
#
# It will, for each prompt in your Markdown file:
#   1. Set the MODEL    (e.g. "Nano Banana Pro")
#   2. Set the QUALITY  (1K / 2K / 4K)
#   3. Set the ASPECT   (e.g. 9:16)
#   4. Ensure UNLIMITED is ON
#   5. Type the prompt and click generate
#   6. Wait, then move to the next prompt
#
# PREREQUISITES (one-time):
#   1. Chrome open & logged in, with a tab on: higgsfield.ai/ai/image
#   2. Chrome menu -> View -> Developer -> "Allow JavaScript from Apple Events" (checked)
#   3. Terminal granted Accessibility permission
#      (System Settings -> Privacy & Security -> Accessibility)
#
# USAGE:
#   ./higgsfield_agent.sh [PROMPTS_FILE] [BATCH] [WAIT_SECONDS]
#     PROMPTS_FILE  .md file with numbered prompts   (default: image_prompts.md)
#     BATCH         1, 2, ... (8 prompts each) or all (default: 1)
#     WAIT_SECONDS  wait after each generation       (default: 50)
#
#   Settings (model/quality/aspect) can be overridden via env vars or by
#   editing the CONFIG block below.
#     MODEL="GPT Image 2" QUALITY=4K ASPECT=1:1 ./higgsfield_agent.sh
# =============================================================================

set -uo pipefail

# =============================================================================
#   CONFIG  —  edit these defaults to change the agent's behavior
# =============================================================================
AGENT_NAME="${AGENT_NAME:-PixelPitch}"      # The agent's name
MODEL="${MODEL:-Nano Banana Pro}"           # Model name as shown on the site
QUALITY="${QUALITY:-1K}"                    # 1K | 2K | 4K
ASPECT="${ASPECT:-9:16}"                     # e.g. 9:16 | 16:9 | 1:1
UNLIMITED="${UNLIMITED:-on}"                 # on | off
BATCH_SIZE="${BATCH_SIZE:-8}"                # prompts per batch
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROMPTS_FILE="${1:-$SCRIPT_DIR/image_prompts.md}"
BATCH="${2:-1}"
WAIT_SECONDS="${3:-50}"
URL_MATCH="higgsfield.ai/ai/image"

NL=$'\n'

banner() {
  echo "======================================================"
  echo "  Agent : $AGENT_NAME"
  echo "  Model : $MODEL   Quality: $QUALITY   Aspect: $ASPECT   Unlimited: $UNLIMITED"
  echo "  File  : $PROMPTS_FILE"
  echo "======================================================"
}

# ---- Run a JS snippet in the Higgsfield tab, return its result -------------
run_js() {
  local js="$1"
  osascript <<APPLE
tell application "Google Chrome"
  set targetTabIndex to 0
  set targetWindow to null
  repeat with w in windows
    set tIdx to 0
    repeat with t in tabs of w
      set tIdx to tIdx + 1
      if URL of t contains "$URL_MATCH" then
        set targetTabIndex to tIdx
        set targetWindow to w
      end if
    end repeat
  end repeat
  if targetWindow is null then
    return "NO_TAB"
  end if
  set active tab index of targetWindow to targetTabIndex
  set index of targetWindow to 1
  activate
  return (execute (tab targetTabIndex of targetWindow) javascript "$js")
end tell
APPLE
}

# ---- Send keystrokes via System Events (needed for Lexical editor) --------
send_keys_type() {
  # $1 = literal text to type
  local text="$1"
  osascript <<APPLE
tell application "System Events"
  keystroke "a" using command down
  delay 0.2
  key code 51
  delay 0.3
  keystroke "$text"
  delay 0.4
end tell
APPLE
}

press_escape() { osascript -e 'tell application "System Events" to key code 53'; }

# ---- Setting helpers -------------------------------------------------------
set_model() {
  local cur
  cur=$(run_js "(function(){var b=[...document.querySelectorAll('button')].find(function(x){return x.innerText.trim().indexOf('$MODEL')===0;}); return b?'ALREADY':'NEED';})()")
  if [[ "$cur" == "ALREADY" ]]; then echo "  model already: $MODEL"; return; fi
  # open the model picker (the toolbar model button is the one whose text isn't a ratio/quality and isn't Unlimited/Draw)
  run_js "(function(){var btns=[...document.querySelectorAll('button')]; var mb=btns.find(function(x){var t=x.innerText.trim(); return t && !/^[0-9]+:[0-9]+\$/.test(t) && !/^(1K|2K|4K)\$/.test(t) && t.indexOf('Unlimited')!==0 && t.indexOf('Draw')!==0 && t.indexOf('Boost')!==0 && t.indexOf('Buy')!==0 && t.indexOf('History')!==0 && t.indexOf('Community')!==0 && t.indexOf('Plugins')!==0 && t.indexOf('1/')!==0;}); if(mb)mb.click(); return mb?'opened':'no-model-btn';})()" >/dev/null
  sleep 1.2
  local res
  res=$(run_js "(function(){var dlg=document.querySelector('[role=dialog],[data-state=open]')||document; var target=null; dlg.querySelectorAll('*').forEach(function(el){var d=''; el.childNodes.forEach(function(n){if(n.nodeType===3)d+=n.textContent;}); if(d.trim()==='$MODEL') target=el;}); if(!target) return 'NOT_FOUND'; var e=target; for(var i=0;i<6&&e;i++){ if(e.tagName==='BUTTON'){e.click(); return 'SELECTED';} e=e.parentElement;} target.click(); return 'CLICKED_TEXT';})()")
  echo "  model -> $MODEL ($res)"
  press_escape; sleep 0.4
}

set_quality() {
  # open quality dropdown
  run_js "(function(){var b=[...document.querySelectorAll('button')].find(function(x){return /^(1K|2K|4K)\$/.test(x.innerText.trim());}); if(b)b.click(); return b?'opened':'no-q-btn';})()" >/dev/null
  sleep 0.7
  local res
  res=$(run_js "(function(){var o=[...document.querySelectorAll('button[role=option]')].find(function(b){return b.innerText.trim().indexOf('$QUALITY')===0;}); if(!o) return 'NOT_FOUND'; o.click(); return 'OK';})()")
  echo "  quality -> $QUALITY ($res)"
  sleep 0.4
}

set_aspect() {
  run_js "(function(){var b=[...document.querySelectorAll('button')].find(function(x){return /^[0-9]+:[0-9]+\$/.test(x.innerText.trim());}); if(b)b.click(); return b?'opened':'no-ar-btn';})()" >/dev/null
  sleep 0.7
  local res
  res=$(run_js "(function(){var o=[...document.querySelectorAll('button[role=option]')].find(function(b){return b.innerText.trim().indexOf('$ASPECT')===0;}); if(!o) return 'NOT_FOUND'; o.click(); return 'OK';})()")
  echo "  aspect -> $ASPECT ($res)"
  sleep 0.4
}

ensure_unlimited() {
  local want="true"; [[ "$UNLIMITED" == "off" ]] && want="false"
  local res
  res=$(run_js "(function(){var sw=document.querySelector('[role=switch]'); if(!sw) return 'NO_SWITCH'; var on=(sw.getAttribute('aria-checked')==='true'||sw.getAttribute('data-state')==='checked'); if(String(on)!=='$want'){sw.click(); return 'TOGGLED';} return 'OK';})()")
  echo "  unlimited -> $UNLIMITED ($res)"
  sleep 0.3
}

focus_prompt() {
  run_js "(function(){var e=document.querySelector('[contenteditable]'); e.click(); e.focus(); return 'ok';})()" >/dev/null
  sleep 0.4
}

click_generate() {
  run_js "(function(){var b=[...document.querySelectorAll('button')]; var f=false; b.forEach(function(x){ if(!f && x.innerText && x.innerText.trim().indexOf('Unlimited')===0 && x.offsetWidth>120){ x.click(); f=true; } }); if(!f){ b.forEach(function(x){ if(!f && x.innerText && x.innerText.trim().indexOf('Unlimited')===0){x.click(); f=true;} }); } return f?'clicked':'not-found';})()"
}

# =============================================================================
#   MAIN
# =============================================================================
banner

[[ -f "$PROMPTS_FILE" ]] || { echo "ERROR: prompts file not found: $PROMPTS_FILE"; exit 1; }

ALL_PROMPTS=()
while IFS= read -r line; do
  ALL_PROMPTS+=("$line")
done < <(grep -E '^[0-9]+\. ' "$PROMPTS_FILE" | sed -E 's/^[0-9]+\. //')
TOTAL=${#ALL_PROMPTS[@]}
[[ $TOTAL -gt 0 ]] || { echo "ERROR: no numbered prompts found in $PROMPTS_FILE"; exit 1; }
echo "Found $TOTAL prompts."

# which prompts to run
declare -a RUN_INDICES
if [[ "$BATCH" == "all" ]]; then
  for ((i=0; i<TOTAL; i++)); do RUN_INDICES+=("$i"); done
else
  START=$(( (BATCH - 1) * BATCH_SIZE )); END=$(( START + BATCH_SIZE ))
  for ((i=START; i<END && i<TOTAL; i++)); do RUN_INDICES+=("$i"); done
  [[ ${#RUN_INDICES[@]} -gt 0 ]] || { echo "ERROR: batch $BATCH empty ($TOTAL prompts total)"; exit 1; }
fi
echo "Running ${#RUN_INDICES[@]} prompt(s). Wait: ${WAIT_SECONDS}s each.${NL}"

# verify tab + apply settings once
[[ "$(run_js "'ping'")" != "NO_TAB" ]] || { echo "ERROR: no Chrome tab on $URL_MATCH"; exit 1; }

echo "Applying settings..."
set_model
set_quality
set_aspect
ensure_unlimited
echo ""

COUNT=0; N=${#RUN_INDICES[@]}
for idx in "${RUN_INDICES[@]}"; do
  COUNT=$((COUNT+1)); PROMPT="${ALL_PROMPTS[$idx]}"; PNUM=$((idx+1))
  echo "=== [$COUNT/$N] prompt #$PNUM ==="
  echo "    $PROMPT"
  focus_prompt
  send_keys_type "$PROMPT"
  sleep 0.3
  echo "    $(click_generate)"
  echo "    waiting ${WAIT_SECONDS}s..."
  sleep "$WAIT_SECONDS"
  echo "    done.${NL}"
done

echo "=== $AGENT_NAME finished: $N image(s) generated. Check the History tab. ==="
