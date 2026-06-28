#!/usr/bin/env bash

set -euo pipefail

readonly DEFAULT_PROMPTS_FILE="image_prompts.md"
readonly DEFAULT_BATCH="1"
readonly DEFAULT_WAIT_SECONDS="50"
readonly BATCH_SIZE=8
readonly TARGET_URL_FRAGMENT="higgsfield.ai/ai/image"

usage() {
  cat <<'EOF'
Usage: ./higgsfield_agent.sh [PROMPTS_FILE] [BATCH] [WAIT_SECONDS]

  PROMPTS_FILE  Markdown file containing numbered, single-line prompts
                (default: image_prompts.md)
  BATCH         1, 2, ... for groups of eight prompts, or "all"
                (default: 1)
  WAIT_SECONDS  Seconds to wait between generations (default: 50)
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

focus_prompt_editor() {
  osascript <<APPLESCRIPT
tell application "Google Chrome"
  if (count of windows) is 0 then return "NO_TAB"

  repeat with windowIndex from 1 to count of windows
    set candidateWindow to window windowIndex
    repeat with tabIndex from 1 to count of tabs of candidateWindow
      set candidateTab to tab tabIndex of candidateWindow
      if (URL of candidateTab contains "${TARGET_URL_FRAGMENT}") then
        set active tab index of candidateWindow to tabIndex
        set index of candidateWindow to 1
        activate

        set editorStatus to execute candidateTab javascript "(() => { const selectors = ['[data-lexical-editor=\"true\"]', '[contenteditable=\"true\"]']; const editor = selectors.map((selector) => document.querySelector(selector)).find(Boolean); if (!editor) return 'NO_EDITOR'; editor.scrollIntoView({ block: 'center' }); editor.click(); editor.focus(); return 'OK'; })();"
        return editorStatus
      end if
    end repeat
  end repeat
end tell

return "NO_TAB"
APPLESCRIPT
}

type_prompt() {
  local prompt="$1"

  osascript - "$prompt" <<'APPLESCRIPT'
on run argv
  set promptText to item 1 of argv

  tell application "System Events"
    keystroke "a" using command down
    key code 51
    delay 0.15
    keystroke promptText
  end tell
end run
APPLESCRIPT
}

click_unlimited_generate() {
  osascript <<APPLESCRIPT
tell application "Google Chrome"
  if (count of windows) is 0 then return "NO_TAB"

  repeat with windowIndex from 1 to count of windows
    set candidateWindow to window windowIndex
    repeat with tabIndex from 1 to count of tabs of candidateWindow
      set candidateTab to tab tabIndex of candidateWindow
      if (URL of candidateTab contains "${TARGET_URL_FRAGMENT}") then
        set buttonStatus to execute candidateTab javascript "(() => { const isVisible = (element) => { const style = window.getComputedStyle(element); const rect = element.getBoundingClientRect(); return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0; }; const buttons = [...document.querySelectorAll('button')].filter((button) => isVisible(button) && !button.disabled && button.getAttribute('aria-disabled') !== 'true' && button.getAttribute('role') !== 'switch'); const text = (button) => (button.innerText || button.textContent || '').trim(); const generateButton = buttons.find((button) => /generate/i.test(text(button)) && /unlimited/i.test(text(button))) || buttons.find((button) => /unlimited/i.test(text(button))); if (!generateButton) return 'NO_UNLIMITED_BUTTON'; generateButton.scrollIntoView({ block: 'center' }); generateButton.click(); return 'OK'; })();"
        return buttonStatus
      end if
    end repeat
  end repeat
end tell

return "NO_TAB"
APPLESCRIPT
}

main() {
  if (( $# > 3 )); then
    usage >&2
    exit 2
  fi

  local prompts_file="${1:-$DEFAULT_PROMPTS_FILE}"
  local batch="${2:-$DEFAULT_BATCH}"
  local wait_seconds="${3:-$DEFAULT_WAIT_SECONDS}"

  [[ -f "$prompts_file" ]] || fail "Prompt file not found: $prompts_file"
  command -v osascript >/dev/null 2>&1 || fail "osascript is required; run this agent on macOS."

  if [[ "$batch" != "all" && ! "$batch" =~ ^[1-9][0-9]*$ ]]; then
    fail 'BATCH must be a positive integer or "all".'
  fi

  if [[ ! "$wait_seconds" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    fail "WAIT_SECONDS must be zero or a positive number."
  fi

  local -a prompt_numbers=()
  local -a prompts=()
  local prompt_number
  local prompt

  while IFS=$'\t' read -r prompt_number prompt; do
    [[ -n "$prompt" ]] || continue
    prompt_numbers+=("$prompt_number")
    prompts+=("$prompt")
  done < <(
    awk '
      /^[[:space:]]*[0-9]+\.[[:space:]]+/ {
        line = $0
        sub(/^[[:space:]]*/, "", line)
        number = line
        sub(/\..*$/, "", number)
        sub(/^[0-9]+\.[[:space:]]+/, "", line)
        print number "\t" line
      }
    ' "$prompts_file"
  )

  local prompt_count=${#prompts[@]}
  (( prompt_count > 0 )) || fail "No numbered prompts found in $prompts_file."

  local start_index=0
  local end_index=$prompt_count
  if [[ "$batch" != "all" ]]; then
    local batch_number=$((10#$batch))
    start_index=$(((batch_number - 1) * BATCH_SIZE))
    (( start_index < prompt_count )) || fail "Batch $batch has no prompts in $prompts_file."
    end_index=$((start_index + BATCH_SIZE))
    (( end_index <= prompt_count )) || end_index=$prompt_count
  fi

  local selected_count=$((end_index - start_index))
  printf 'Generating %d prompt(s) from %s (batch: %s).\n' "$selected_count" "$prompts_file" "$batch"
  printf 'Keep Chrome open on https://%s with Unlimited enabled.\n\n' "$TARGET_URL_FRAGMENT"

  local index
  local editor_status
  local button_status
  local completed=0

  for ((index = start_index; index < end_index; index++)); do
    printf '[%d/%d] Prompt %s: %s\n' \
      "$((completed + 1))" "$selected_count" "${prompt_numbers[$index]}" "${prompts[$index]}"

    if ! editor_status="$(focus_prompt_editor)"; then
      fail "Chrome could not be controlled. Enable JavaScript from Apple Events and try again."
    fi

    case "$editor_status" in
      OK) ;;
      NO_TAB) fail "No Chrome tab is open at https://$TARGET_URL_FRAGMENT." ;;
      NO_EDITOR) fail "The Higgsfield prompt editor was not found; the page layout may have changed." ;;
      *) fail "Unexpected editor response: $editor_status" ;;
    esac

    sleep 0.25
    type_prompt "${prompts[$index]}" || fail "Could not type the prompt. Check macOS Accessibility permissions."
    sleep 0.25

    if ! button_status="$(click_unlimited_generate)"; then
      fail "Chrome could not click Generate. Enable JavaScript from Apple Events and try again."
    fi

    case "$button_status" in
      OK) ;;
      NO_TAB) fail "The Higgsfield Chrome tab was closed." ;;
      NO_UNLIMITED_BUTTON) fail "No enabled Unlimited generate button was found. Turn Unlimited on and check the page." ;;
      *) fail "Unexpected generate-button response: $button_status" ;;
    esac

    completed=$((completed + 1))
    printf 'Generation started.\n'

    if (( index + 1 < end_index )); then
      printf 'Waiting %s second(s)...\n\n' "$wait_seconds"
      sleep "$wait_seconds"
    fi
  done

  printf '\nDone. Started %d generation(s).\n' "$completed"
}

main "$@"
