#!/bin/zsh
set -eu
cd -- "${0:A:h}"
python3 queue_agent.py scan
echo ""
echo "This check does not generate videos. Read pending jobs and any errors above."
read -r "?Press Return to close. "
