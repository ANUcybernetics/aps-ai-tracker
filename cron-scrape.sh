#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/ben/projects/aps-ai-transparency-tracker"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scrape-$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

# mise activates tool shims into PATH (jj, uv, node, etc.)
eval "$(/home/ben/.local/bin/mise activate bash)"

cd "$PROJECT_DIR"

echo "=== scrape started at $(date -Iseconds) ===" >> "$LOG_FILE"

/home/ben/.local/bin/claude \
  --dangerously-skip-permissions \
  -p "/scrape" \
  >> "$LOG_FILE" 2>&1

echo "=== scrape finished at $(date -Iseconds) ===" >> "$LOG_FILE"
