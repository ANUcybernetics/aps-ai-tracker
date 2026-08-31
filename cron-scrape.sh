#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/ben/projects/aps-ai-tracker"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scrape-$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

# Keep two months of run logs; they grow without bound otherwise.
find "$LOG_DIR" -name 'scrape-*.log' -mtime +60 -delete

# mise activates tool shims into PATH (uv, node, etc.)
eval "$(/home/ben/.local/bin/mise activate bash)"
# The export step shells out to `claude -p` (found via PATH, unlike the
# absolute-path invocation below), so make sure the user-local bin is on it.
export PATH="/home/ben/.local/bin:$PATH"

cd "$PROJECT_DIR"

echo "=== scrape started at $(date -Iseconds) ===" >> "$LOG_FILE"

# A failed scrape shouldn't abort the run: the export below is a no-op on an
# unchanged corpus and the push still redeploys anything already committed.
# Through agent-run's claude-sub profile, which scrubs ANTHROPIC_* from the
# environment so the run can only ever bill the subscription, and on Sonnet.
/home/ben/.dotfiles/bin/agent-run \
  --profile claude-sub \
  --model sonnet \
  --bypass-permissions \
  --cwd "$PROJECT_DIR" \
  "/scrape" \
  < /dev/null >> "$LOG_FILE" 2>&1 || echo "scrape failed (continuing)" >> "$LOG_FILE"

echo "=== scrape finished at $(date -Iseconds) ===" >> "$LOG_FILE"

# Classify today's changed revisions and profile the changed statements. This
# is the one place a model is called: the export shells out to `claude -p`
# (Sonnet, subscription — llm.py scrubs API credentials from the child
# environment), and CI rebuilds the site from the committed caches without any
# model. Unchanged statements are cache hits, so a typical run makes a handful
# of calls or none.
echo "=== export started at $(date -Iseconds) ===" >> "$LOG_FILE"
uv run --group export export >> "$LOG_FILE" 2>&1 || echo "export failed (continuing)" >> "$LOG_FILE"

# Commit the refreshed extraction caches (the only derived artifacts we track);
# generated site JSON is rebuilt in CI.
git add -- .cache/changes.json .cache/profiles.json 2>/dev/null || true
if ! git diff --cached --quiet -- .cache/changes.json .cache/profiles.json; then
  git commit -m "analysis: refresh extraction caches after scrape" >> "$LOG_FILE" 2>&1
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
# This is the run's only push: the scrape skill commits but does not push, so
# the day's statements and their classifications always deploy together.
# (Overrides the global manual-push default for this repo; weddle needs push
# credentials for origin.)
echo "=== push at $(date -Iseconds) ===" >> "$LOG_FILE"
git push >> "$LOG_FILE" 2>&1 || echo "push failed" >> "$LOG_FILE"

# Manual agencies sit behind a bot challenge no HTTP client can pass, so a
# person opening the page is the only thing that catches a change in them.
# `stale-manual` lists the ones due (see verify.py); each becomes an nb todo,
# keyed by abbr so a still-open todo is never raised twice. This is the one
# step that reaches outside the repo, which is why it lives here rather than
# in the package: the tracker shouldn't know about Ben's notebook.
echo "=== manual-check todos at $(date -Iseconds) ===" >> "$LOG_FILE"
open_todos=$(nb todos open --no-color 2>/dev/null || true)
while IFS=$'\t' read -r abbr name url; do
  [ -n "$abbr" ] || continue
  key="aps-ai-tracker:${abbr}"
  case "$open_todos" in
    *"$key"*)
      echo "todo already open for ${abbr}" >> "$LOG_FILE"
      continue
      ;;
  esac
  nb todo add "${key} hand-check ${name}'s AI transparency statement at ${url} (the site blocks the scraper), then set last_verified in agencies.toml" \
    >> "$LOG_FILE" 2>&1 || echo "todo add failed for ${abbr}" >> "$LOG_FILE"
done < <(uv run stale-manual 2>> "$LOG_FILE" || true)

echo "=== run finished at $(date -Iseconds) ===" >> "$LOG_FILE"
