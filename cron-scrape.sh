#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/ben/projects/aps-ai-tracker"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scrape-$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

# Keep two months of run logs; they grow without bound otherwise.
find "$LOG_DIR" -name 'scrape-*.log' -mtime +60 -delete

# mise activates tool shims into PATH (jj, uv, node, etc.)
eval "$(/home/ben/.local/bin/mise activate bash)"

cd "$PROJECT_DIR"

echo "=== scrape started at $(date -Iseconds) ===" >> "$LOG_FILE"

# A failed scrape shouldn't abort the run: the export below is a no-op on an
# unchanged corpus and the push still redeploys anything already committed.
/home/ben/.local/bin/claude \
  --dangerously-skip-permissions \
  -p "/scrape" \
  >> "$LOG_FILE" 2>&1 || echo "scrape failed (continuing)" >> "$LOG_FILE"

echo "=== scrape finished at $(date -Iseconds) ===" >> "$LOG_FILE"

# Refresh embeddings for any changed statements. This is the one place the
# OpenAI key is used (from the environment); CI rebuilds the site from the
# committed cache without a key. Unchanged statements are cache hits, so a
# typical run makes zero API calls.
echo "=== export started at $(date -Iseconds) ===" >> "$LOG_FILE"
uv run --group export export >> "$LOG_FILE" 2>&1 || echo "export failed (continuing)" >> "$LOG_FILE"

# Commit the refreshed embeddings cache (the only derived artifact we track);
# generated site JSON is rebuilt in CI.
git add -- .cache/embeddings.json 2>/dev/null || true
if ! git diff --cached --quiet -- .cache/embeddings.json; then
  git commit -m "embeddings: refresh cache after scrape" >> "$LOG_FILE" 2>&1
fi

# Sync the corpus to the atproto network (the apsaitracker account; app
# password comes from APSAITRACKER_BSKY_TOKEN in the mise env) and announce
# substantive changes as skeets. Reads the export's generated JSON, so it must
# run after the export step; on an unchanged corpus it puts nothing.
echo "=== atproto publish at $(date -Iseconds) ===" >> "$LOG_FILE"
(cd site && pnpm run atproto:publish -- --write --crosspost) >> "$LOG_FILE" 2>&1 \
  || echo "atproto publish failed (continuing)" >> "$LOG_FILE"

# Commit the publish state (record hashes) and syndication ledger (announced
# skeets) alongside the embeddings cache.
git add -- atproto-state.json atproto-syndication.json 2>/dev/null || true
if ! git diff --cached --quiet -- atproto-state.json atproto-syndication.json; then
  git commit -m "atproto: update publish state after scrape" >> "$LOG_FILE" 2>&1
fi

# Publish: push so the GitHub Pages workflow rebuilds and deploys the site.
# (Overrides the global manual-push default for this repo; weddle needs push
# credentials for origin.)
echo "=== push at $(date -Iseconds) ===" >> "$LOG_FILE"
git push >> "$LOG_FILE" 2>&1 || echo "push failed" >> "$LOG_FILE"

echo "=== run finished at $(date -Iseconds) ===" >> "$LOG_FILE"
