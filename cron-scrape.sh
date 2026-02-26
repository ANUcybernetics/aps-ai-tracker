#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/ben/Code/aps-ai-transparency-tracker"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scrape-$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

# clear nested-session guard (set when run from inside claude code)
unset CLAUDECODE 2>/dev/null || true

# mise activates tool shims into PATH (jj, uv, node, etc.)
eval "$(/home/ben/.local/bin/mise activate bash)"

cd "$PROJECT_DIR"

echo "=== scrape started at $(date -Iseconds) ===" >> "$LOG_FILE"

/home/ben/.local/bin/claude \
  --dangerously-skip-permissions \
  -p "/scrape" \
  >> "$LOG_FILE" 2>&1

echo "=== scrape finished at $(date -Iseconds) ===" >> "$LOG_FILE"
