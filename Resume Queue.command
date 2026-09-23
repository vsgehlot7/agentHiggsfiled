#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ -f PAUSE ]]; then
  mkdir -p state
  mv -f -- PAUSE state/last-pause
fi
echo "Queue resumed. Codex will check on its next scheduled run."
