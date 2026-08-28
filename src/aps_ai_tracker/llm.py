"""Claude-backed structured extraction shared by the analysis modules.

Every extraction is one prompt with a Pydantic output schema, and every result
is cached on disk under `.cache/` keyed by a content hash plus the caller's
schema version. The caches are committed, so the nightly export on weddle makes
a handful of calls for the statements that changed that day and CI makes none.
Without a usable backend the functions degrade to the cache rather than failing
the build.

Two interchangeable backends, chosen with `APS_LLM_BACKEND`:

- `cli` (default): shells out to `claude -p --json-schema …`, so the nightly
  run uses the same Claude Code subscription as the `/scrape` skill and no
  metered key is involved
- `api`: the Anthropic SDK against `ANTHROPIC_API_KEY`, for environments
  without a logged-in Claude Code
"""

import json
import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from .scraper import REPO_ROOT, atomic_write_text, logger

MODEL = "claude-opus-5"
CACHE_DIR = REPO_ROOT / ".cache"
# A handful of concurrent requests is plenty: the backfill is a few hundred calls
# once, and a daily run is one or two. Keeps well inside rate limits.
_WORKERS = 4
# One statement, one structured answer. Generous because a `claude -p` process
# also pays the CLI's start-up cost; a hang still fails loudly inside the
# systemd timeout instead of stalling the nightly run.
_CLI_TIMEOUT_SECONDS = 600


def backend() -> str:
    return os.environ.get("APS_LLM_BACKEND", "cli")


def api_available() -> bool:
    """Whether the selected backend can actually make a call."""
    if backend() == "api":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return shutil.which("claude") is not None


def load_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict) -> None:
    """Write one entry per line so a changed statement is a one-line git diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(cache.items())
    lines = ["{"]
    for i, (key, value) in enumerate(items):
        tail = "," if i < len(items) - 1 else ""
        lines.append(
            f"  {json.dumps(key)}: "
            f"{json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}{tail}"
        )
    lines.append("}\n")
    atomic_write_text(path, "\n".join(lines))


# --- backends ---------------------------------------------------------------


def _extract_cli[T: BaseModel](
    system: str, user: str, schema: type[T], effort: str
) -> T:
    """`claude -p` with a JSON schema; the prompt goes in on stdin.

    `--system-prompt` replaces Claude Code's own (large) system prompt and
    `--tools ""` leaves the model nothing to do but answer, so a call costs
    roughly what the SDK call would. Sessions are not persisted.
    """
    cmd = [
        "claude",
        "-p",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--model",
        MODEL,
        "--effort",
        effort,
        "--tools",
        "",
        "--system-prompt",
        system,
        "--json-schema",
        json.dumps(schema.model_json_schema()),
    ]
    result = subprocess.run(
        cmd,
        input=user,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_CLI_TIMEOUT_SECONDS,
        check=False,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {result.returncode}: {result.stderr.strip()[:500]}"
        )
    payload = json.loads(result.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(payload.get('result'))[:500]}")
    structured = payload.get("structured_output")
    if structured is None:
        raise RuntimeError("claude -p returned no structured_output")
    return schema.model_validate(structured)


_client = None


def _client_instance():
    """Lazy import: anthropic lives in the optional `export` dependency group."""
    global _client
    if _client is None:
        from anthropic import Anthropic

        # The SDK's HTTP layer logs every request at INFO; that is noise in a
        # nightly log that already reports per-batch counts.
        for name in ("httpx", "httpx2"):
            logging.getLogger(name).setLevel(logging.WARNING)
        _client = Anthropic()
    return _client


def _extract_api[T: BaseModel](
    system: str, user: str, schema: type[T], effort: str
) -> T:
    """One structured-output Messages API call. Raises on refusal or truncation.

    The system prompt is marked cacheable: it is identical across every call of
    a given extractor, so the (long) instructions are read from cache and only
    the statement text is billed at full rate.
    """
    response = _client_instance().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"extraction stopped with {response.stop_reason}")
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("extraction returned no parsed output")
    return parsed


def extract[T: BaseModel](
    system: str, user: str, schema: type[T], *, effort: str = "medium"
) -> T:
    """One structured extraction through the selected backend."""
    if backend() == "api":
        return _extract_api(system, user, schema, effort)
    return _extract_cli(system, user, schema, effort)


def extract_many[T: BaseModel](
    jobs: dict[str, tuple[str, str, type[T]]], *, effort: str = "medium"
) -> dict[str, T]:
    """Run `extract` for each {key: (system, user, schema)} concurrently.

    A failed job is logged and omitted (so it is retried next run) rather than
    aborting the whole export.
    """
    if not jobs:
        return {}
    results: dict[str, T] = {}

    def run(item: tuple[str, tuple[str, str, type[T]]]) -> tuple[str, T | None]:
        key, (system, user, schema) = item
        try:
            return key, extract(system, user, schema, effort=effort)
        except Exception as exc:  # noqa: BLE001 - surfaced in the log, retried next run
            logger.warning("Extraction failed for %s: %s", key, exc)
            return key, None

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for key, value in pool.map(run, sorted(jobs.items())):
            if value is not None:
                results[key] = value
    logger.info(
        "Extracted %d/%d via %s (%s backend)", len(results), len(jobs), MODEL, backend()
    )
    return results
